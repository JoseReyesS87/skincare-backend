import os
import pandas as pd
import requests
from datetime import datetime
import json
import time
from typing import Dict, List, Optional
import logging

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ShopifySync:
    def __init__(self):
        # Obtener credenciales desde variables de entorno
        self.shop_domain = os.environ.get('SHOPIFY_SHOP_DOMAIN')
        self.access_token = os.environ.get('SHOPIFY_ACCESS_TOKEN')
        self.api_version = '2024-01'  # Actualiza según tu versión
        
        if not self.shop_domain or not self.access_token:
            raise ValueError("Faltan las credenciales de Shopify en las variables de entorno")
        
        self.base_url = f"https://{self.shop_domain}/admin/api/{self.api_version}"
        self.headers = {
            'X-Shopify-Access-Token': self.access_token,
            'Content-Type': 'application/json'
        }
        
        # Configurar la base de datos o archivo donde guardarás los datos
        self.data_file = 'shopify_products.json'  # Puedes cambiar esto a una DB
        
    def get_all_products(self) -> List[Dict]:
        """Obtiene todos los productos de Shopify con paginación"""
        products = []
        url = f"{self.base_url}/products.json"
        params = {
            'limit': 250,  # Máximo permitido por Shopify
            'fields': 'id,title,handle,vendor,product_type,created_at,updated_at,variants,images'
        }
        
        while url:
            try:
                response = requests.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                
                data = response.json()
                products.extend(data.get('products', []))
                
                # Verificar si hay más páginas
                link_header = response.headers.get('Link', '')
                url = self._get_next_page_url(link_header)
                params = {}  # Los params solo se usan en la primera petición
                
                # Respetar rate limits
                time.sleep(0.5)
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error obteniendo productos: {e}")
                break
                
        logger.info(f"Total de productos obtenidos: {len(products)}")
        return products
    
    def get_inventory_levels(self) -> Dict[str, int]:
        """Obtiene los niveles de inventario actuales"""
        inventory_levels = {}
        url = f"{self.base_url}/inventory_levels.json"
        params = {'limit': 250}
        
        while url:
            try:
                response = requests.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                
                data = response.json()
                for item in data.get('inventory_levels', []):
                    inventory_item_id = item.get('inventory_item_id')
                    available = item.get('available', 0)
                    inventory_levels[str(inventory_item_id)] = available
                
                # Paginación
                link_header = response.headers.get('Link', '')
                url = self._get_next_page_url(link_header)
                params = {}
                
                time.sleep(0.5)
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error obteniendo inventario: {e}")
                break
                
        logger.info(f"Niveles de inventario obtenidos: {len(inventory_levels)}")
        return inventory_levels
    
    def _get_next_page_url(self, link_header: str) -> Optional[str]:
        """Extrae la URL de la siguiente página del header Link"""
        if not link_header:
            return None
            
        links = link_header.split(',')
        for link in links:
            if 'rel="next"' in link:
                url = link.split(';')[0].strip('<> ')
                return url
        return None
    
    def process_products_data(self, products: List[Dict], inventory: Dict[str, int]) -> pd.DataFrame:
        """Procesa los productos y crea el DataFrame"""
        processed_data = []
        
        for product in products:
            base_info = {
                'product_id': product.get('id'),
                'title': product.get('title'),
                'handle': product.get('handle'),
                'vendor': product.get('vendor'),
                'product_type': product.get('product_type'),
                'created_at': product.get('created_at'),
                'updated_at': product.get('updated_at'),
                'image_url': product.get('images', [{}])[0].get('src') if product.get('images') else None
            }
            
            # Procesar variantes
            for variant in product.get('variants', []):
                variant_data = base_info.copy()
                variant_data.update({
                    'variant_id': variant.get('id'),
                    'sku': variant.get('sku'),
                    'price': variant.get('price'),
                    'compare_at_price': variant.get('compare_at_price'),
                    'inventory_item_id': variant.get('inventory_item_id'),
                    'stock': inventory.get(str(variant.get('inventory_item_id')), 0),
                    'barcode': variant.get('barcode'),
                    'weight': variant.get('weight'),
                    'weight_unit': variant.get('weight_unit'),
                    'option1': variant.get('option1'),
                    'option2': variant.get('option2'),
                    'option3': variant.get('option3')
                })
                processed_data.append(variant_data)
        
        df = pd.DataFrame(processed_data)
        logger.info(f"DataFrame creado con {len(df)} filas")
        return df
    
    def save_data(self, df: pd.DataFrame):
        """Guarda los datos procesados"""
        # Opción 1: Guardar como JSON (simple para empezar)
        df.to_json(self.data_file, orient='records', indent=2)
        logger.info(f"Datos guardados en {self.data_file}")
        
        # Opción 2: Guardar en una base de datos PostgreSQL (si tienes una en Render)
        # from sqlalchemy import create_engine
        # engine = create_engine(os.environ.get('DATABASE_URL'))
        # df.to_sql('products', engine, if_exists='replace', index=False)
    
    def check_for_changes(self, new_df: pd.DataFrame) -> Dict[str, List]:
        """Compara con datos anteriores para detectar cambios"""
        changes = {'new_products': [], 'stock_changes': [], 'price_changes': []}
        
        if os.path.exists(self.data_file):
            try:
                old_df = pd.read_json(self.data_file)
                
                # Detectar nuevos productos
                new_products = new_df[~new_df['variant_id'].isin(old_df['variant_id'])]
                changes['new_products'] = new_products.to_dict('records')
                
                # Detectar cambios de stock
                merged = new_df.merge(old_df, on='variant_id', suffixes=('_new', '_old'))
                stock_changes = merged[merged['stock_new'] != merged['stock_old']]
                changes['stock_changes'] = stock_changes[['variant_id', 'title_new', 'sku_new', 'stock_old', 'stock_new']].to_dict('records')
                
                # Detectar cambios de precio
                price_changes = merged[merged['price_new'] != merged['price_old']]
                changes['price_changes'] = price_changes[['variant_id', 'title_new', 'sku_new', 'price_old', 'price_new']].to_dict('records')
                
            except Exception as e:
                logger.error(f"Error comparando cambios: {e}")
        
        return changes
    
    def sync_products(self):
        """Función principal de sincronización para productos"""
        logger.info("Iniciando sincronización de productos...")
        
        try:
            # Obtener productos
            products = self.get_all_products()
            
            # Obtener inventario
            inventory = self.get_inventory_levels()
            
            # Procesar datos
            df = self.process_products_data(products, inventory)
            
            # Detectar cambios
            changes = self.check_for_changes(df)
            
            # Registrar cambios
            if changes['new_products']:
                logger.info(f"Nuevos productos detectados: {len(changes['new_products'])}")
            if changes['stock_changes']:
                logger.info(f"Cambios de stock detectados: {len(changes['stock_changes'])}")
            if changes['price_changes']:
                logger.info(f"Cambios de precio detectados: {len(changes['price_changes'])}")
            
            # Guardar datos
            self.save_data(df)
            
            logger.info("Sincronización completada exitosamente")
            
            # Opcional: Enviar notificaciones sobre cambios importantes
            # self.send_notifications(changes)
            
        except Exception as e:
            logger.error(f"Error en sincronización: {e}")
            raise
    
    def sync_inventory_only(self):
        """Función rápida solo para actualizar inventario"""
        logger.info("Iniciando actualización rápida de inventario...")
        
        try:
            # Cargar datos existentes
            if not os.path.exists(self.data_file):
                logger.warning("No hay datos previos, ejecutando sincronización completa")
                return self.sync_products()
            
            df = pd.read_json(self.data_file)
            
            # Obtener solo inventario
            inventory = self.get_inventory_levels()
            
            # Actualizar stock en el DataFrame
            df['stock'] = df['inventory_item_id'].astype(str).map(inventory).fillna(0).astype(int)
            
            # Guardar datos actualizados
            self.save_data(df)
            
            logger.info("Actualización de inventario completada")
            
        except Exception as e:
            logger.error(f"Error actualizando inventario: {e}")
            raise


# Funciones para ejecutar según el tipo de sincronización
def run_full_sync():
    """Ejecuta sincronización completa (productos + inventario)"""
    sync = ShopifySync()
    sync.sync_products()

def run_inventory_sync():
    """Ejecuta solo actualización de inventario"""
    sync = ShopifySync()
    sync.sync_inventory_only()

if __name__ == "__main__":
    # Por defecto ejecuta sincronización completa
    run_full_sync()
