import shopify
import json
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Cargar variables de entorno
load_dotenv()

SHOP_NAME = os.getenv('SHOPIFY_SHOP_NAME')
ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')

def get_all_collections():
    """Obtiene todas las colecciones (Custom y Smart Collections)"""
    try:
        all_collections = {}
        
        print("📂 Obteniendo Custom Collections...")
        # Obtener Custom Collections
        custom_collections = shopify.CustomCollection.find(limit=250)
        for collection in custom_collections:
            all_collections[str(collection.id)] = {
                'id': str(collection.id),
                'handle': collection.handle,
                'title': collection.title,
                'type': 'custom'
            }
        
        print("📂 Obteniendo Smart Collections...")
        # Obtener Smart Collections
        smart_collections = shopify.SmartCollection.find(limit=250)
        for collection in smart_collections:
            all_collections[str(collection.id)] = {
                'id': str(collection.id),
                'handle': collection.handle,
                'title': collection.title,
                'type': 'smart'
            }
        
        print(f"✅ Encontradas {len(all_collections)} colecciones")
        for col_id, col_data in all_collections.items():
            print(f"   - {col_data['title']} ({col_data['handle']}) [{col_data['type']}]")
        
        return all_collections
        
    except Exception as e:
        print(f"❌ Error obteniendo colecciones: {e}")
        return {}

def get_product_collections_batch(products, all_collections):
    """Obtiene colecciones de productos en batch para mejor performance"""
    product_collections_map = {}
    
    print("🔗 Mapeando productos a colecciones...")
    
    # Para cada colección, obtener sus productos
    for collection_id, collection_data in all_collections.items():
        try:
            print(f"   Procesando colección: {collection_data['title']}")
            
            # Obtener productos de esta colección
            try:
                if collection_data['type'] == 'custom':
                    collection_products = shopify.Product.find(collection_id=collection_id, limit=250)
                else:  # smart collection
                    collection_products = shopify.Product.find(collection_id=collection_id, limit=250)
            except Exception as inner_e:
                print(f"     ⚠️ Error obteniendo productos de colección: {inner_e}")
                continue
            
            # Mapear productos a colecciones
            for product in collection_products:
                product_id = str(product.id)
                
                if product_id not in product_collections_map:
                    product_collections_map[product_id] = []
                
                product_collections_map[product_id].append({
                    'collection_id': collection_id,
                    'collection_handle': collection_data['handle'],
                    'collection_title': collection_data['title']
                })
            
            print(f"     - {len(collection_products)} productos en esta colección")
            
        except Exception as e:
            print(f"❌ Error procesando colección {collection_data['title']}: {e}")
            continue
    
    return product_collections_map

def get_product_sales_data():
    """Obtiene datos de ventas históricas por producto de los últimos 90 días"""
    
    print("📊 Obteniendo datos de ventas históricas...")
    
    sales_by_product = {}
    
    try:
        # Fecha de hace 90 días
        since_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        
        # Obtener todas las órdenes desde esa fecha
        print(f"   Buscando órdenes desde: {since_date}")
        
        orders = shopify.Order.find(
            status='any',
            created_at_min=since_date,
            limit=250
        )
        
        total_orders_processed = 0
        
        # Procesar primera página
        print(f"   Procesando primera página con {len(orders)} órdenes...")
        
        for order in orders:
            # Solo contar órdenes completadas/pagadas
            if order.financial_status in ['paid', 'partially_paid']:
                total_orders_processed += 1
                
                for line_item in order.line_items:
                    product_id = str(line_item.product_id) if line_item.product_id else 'unknown'
                    variant_id = str(line_item.variant_id) if line_item.variant_id else 'unknown'
                    quantity = line_item.quantity or 0
                    
                    # Crear clave única para producto-variante
                    key = f"{product_id}-{variant_id}"
                    
                    if key not in sales_by_product:
                        sales_by_product[key] = {
                            'product_id': product_id,
                            'variant_id': variant_id,
                            'total_sold': 0,
                            'order_count': 0,
                            'product_title': line_item.title or 'Unknown'
                        }
                    
                    sales_by_product[key]['total_sold'] += quantity
                    sales_by_product[key]['order_count'] += 1
        
        # Procesar páginas adicionales si existen
        page_num = 2
        while orders.has_next_page():
            print(f"   Procesando página {page_num}...")
            orders = orders.next_page()
            
            for order in orders:
                if order.financial_status in ['paid', 'partially_paid']:
                    total_orders_processed += 1
                    
                    for line_item in order.line_items:
                        product_id = str(line_item.product_id) if line_item.product_id else 'unknown'
                        variant_id = str(line_item.variant_id) if line_item.variant_id else 'unknown'
                        quantity = line_item.quantity or 0
                        
                        key = f"{product_id}-{variant_id}"
                        
                        if key not in sales_by_product:
                            sales_by_product[key] = {
                                'product_id': product_id,
                                'variant_id': variant_id,
                                'total_sold': 0,
                                'order_count': 0,
                                'product_title': line_item.title or 'Unknown'
                            }
                        
                        sales_by_product[key]['total_sold'] += quantity
                        sales_by_product[key]['order_count'] += 1
            
            page_num += 1
        
        print(f"✅ Procesadas {total_orders_processed} órdenes pagadas")
        print(f"✅ Datos de ventas obtenidos para {len(sales_by_product)} variantes")
        
        # Mostrar top 10 productos más vendidos
        sorted_sales = sorted(sales_by_product.items(), 
                            key=lambda x: x[1]['total_sold'], 
                            reverse=True)[:10]
        
        print("\n🏆 TOP 10 PRODUCTOS MÁS VENDIDOS (últimos 90 días):")
        for i, (key, data) in enumerate(sorted_sales, 1):
            print(f"   {i}. {data['product_title']}: {data['total_sold']} unidades vendidas")
        
        return sales_by_product
        
    except Exception as e:
        print(f"❌ Error obteniendo datos de ventas: {e}")
        import traceback
        traceback.print_exc()
        return {}

def calculate_popularity_metrics(variant, product, sales_data):
    """Calcula métricas basadas en ventas históricas REALES"""
    
    stock = variant.inventory_quantity or 0
    variant_id = str(variant.id)
    product_id = str(product.id)
    
    # Obtener datos de ventas para esta variante
    key = f"{product_id}-{variant_id}"
    variant_sales = sales_data.get(key, {})
    
    total_sold = variant_sales.get('total_sold', 0)
    order_count = variant_sales.get('order_count', 0)
    
    # Determinar disponibilidad (basado solo en stock)
    is_available = stock > 0
    
    # Score basado ÚNICAMENTE en cantidad vendida
    if total_sold > 100:
        sales_score = 1.0
    elif total_sold > 50:
        sales_score = 0.9
    elif total_sold > 20:
        sales_score = 0.7
    elif total_sold > 10:
        sales_score = 0.5
    elif total_sold > 5:
        sales_score = 0.3
    elif total_sold > 0:
        sales_score = 0.1
    else:
        sales_score = 0.0
    
    # Score final: score de ventas si está disponible, 0 si no hay stock
    final_ranking_score = sales_score if is_available else 0.0
    
    return {
        'popularity_score': round(sales_score, 3),
        'sales_score': round(sales_score, 3),
        'total_sold': total_sold,
        'order_count': order_count,
        'final_ranking_score': round(final_ranking_score, 3)
    }

def sync_products_with_collections():
    """Función principal de sincronización con colecciones y datos de ventas"""
    
    # Configurar conexión a Shopify
    shopify.ShopifyResource.set_site(f"https://{SHOP_NAME}.myshopify.com/admin/api/2023-10/")
    shopify.ShopifyResource.set_headers({"X-Shopify-Access-Token": ACCESS_TOKEN})
    
    print(f"🚀 Iniciando sincronización de productos con colecciones y ventas...")
    print(f"   Tienda: {SHOP_NAME}")
    print(f"   Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # PASO 1: Obtener todas las colecciones
        print(f"\n📂 PASO 1: Obteniendo colecciones...")
        all_collections = get_all_collections()
        
        # PASO 2: Obtener todos los productos
        print(f"\n📦 PASO 2: Obteniendo productos...")
        products = shopify.Product.find(limit=250)
        
        # Manejar paginación si hay más de 250 productos
        all_products = list(products)
        while products.has_next_page():
            products = products.next_page()
            all_products.extend(products)
        
        print(f"✅ Encontrados {len(all_products)} productos en total")
        
        # PASO 3: Obtener datos de ventas
        print(f"\n📊 PASO 3: Obteniendo datos de ventas...")
        sales_data = get_product_sales_data()
        
        # PASO 4: Mapear productos a colecciones
        print(f"\n🔗 PASO 4: Mapeando productos a colecciones...")
        product_collections_map = get_product_collections_batch(all_products, all_collections)
        
        # PASO 5: Procesar productos y variantes
        print(f"\n⚙️ PASO 5: Procesando productos y variantes...")
        products_data = []
        
        for i, product in enumerate(all_products):
            if i % 50 == 0:  # Mostrar progreso cada 50 productos
                print(f"   Procesando producto {i+1}/{len(all_products)}")
            
            # Obtener colecciones de este producto
            product_collections = product_collections_map.get(str(product.id), [])
            
            for variant in product.variants:
                # Calcular métricas de popularidad con datos de ventas
                popularity_metrics = calculate_popularity_metrics(variant, product, sales_data)
                
                product_info = {
                    # Datos básicos del producto
                    'product_id': str(product.id),
                    'variant_id': str(variant.id),
                    'title': product.title,
                    'sku': variant.sku or '',
                    'price': float(variant.price) if variant.price else 0,
                    'stock': variant.inventory_quantity or 0,
                    'product_type': product.product_type or '',
                    'vendor': product.vendor or '',
                    'tags': product.tags.split(', ') if product.tags else [],
                    'tags_str': product.tags or '',  # Para compatibilidad con app.py
                    'handle': product.handle,
                    'image_url': str(product.images[0].src) if product.images else '',
                    'available': (variant.inventory_quantity or 0) > 0,
                    
                    # DATOS DE COLECCIONES (requeridos por el nuevo pipeline)
                    'collections': product_collections,
                    'collection_handles': [col['collection_handle'] for col in product_collections],
                    'collection_titles': [col['collection_title'] for col in product_collections],
                    
                    # MÉTRICAS DE POPULARIDAD (con datos de ventas reales)
                    **popularity_metrics
                }
                
                products_data.append(product_info)
        
        # PASO 6: Crear backup del archivo anterior (si existe)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if os.path.exists('shopify_products.json'):
            backup_filename = f'shopify_products_backup_{timestamp}.json'
            os.rename('shopify_products.json', backup_filename)
            print(f"\n💾 Backup creado: {backup_filename}")
        
        # PASO 7: Guardar datos nuevos
        print(f"\n💾 PASO 6: Guardando datos...")
        with open('shopify_products.json', 'w', encoding='utf-8') as f:
            json.dump(products_data, f, ensure_ascii=False, indent=2)
        
        # PASO 8: Mostrar estadísticas finales
        print(f"\n✅ SINCRONIZACIÓN COMPLETADA")
        print(f"   📦 Total productos/variantes: {len(products_data)}")
        print(f"   📂 Total colecciones: {len(all_collections)}")
        print(f"   💾 Archivo guardado: shopify_products.json")
        
        # Estadísticas de ventas
        products_with_sales = sum(1 for p in products_data if p.get('total_sold', 0) > 0)
        total_units_sold = sum(p.get('total_sold', 0) for p in products_data)
        
        print(f"\n📊 ESTADÍSTICAS DE VENTAS (últimos 90 días):")
        print(f"   🛒 Productos con ventas: {products_with_sales}")
        print(f"   📦 Total unidades vendidas: {total_units_sold}")
        
        # Estadísticas de colecciones
        products_with_collections = sum(1 for p in products_data if p['collections'])
        products_without_collections = len(products_data) - products_with_collections
        print(f"\n🔗 ESTADÍSTICAS DE COLECCIONES:")
        print(f"   ✅ Productos con colecciones: {products_with_collections}")
        print(f"   ⚠️ Productos sin colecciones: {products_without_collections}")
        
        # Top colecciones por número de productos
        collection_counts = {}
        for product in products_data:
            for collection in product['collection_handles']:
                collection_counts[collection] = collection_counts.get(collection, 0) + 1
        
        print(f"\n📊 TOP 10 COLECCIONES POR NÚMERO DE PRODUCTOS:")
        top_collections = sorted(collection_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        for collection, count in top_collections:
            print(f"   - {collection}: {count} productos")
        
        # Estadísticas de stock y disponibilidad
        available_products = sum(1 for p in products_data if p['available'])
        total_stock = sum(p['stock'] for p in products_data)
        avg_price = sum(p['price'] for p in products_data) / len(products_data) if products_data else 0
        
        print(f"\n📈 ESTADÍSTICAS GENERALES:")
        print(f"   ✅ Productos disponibles: {available_products}")
        print(f"   📦 Stock total: {total_stock}")
        print(f"   💰 Precio promedio: ${avg_price:,.0f}")
        
        # Top 10 productos más vendidos en el archivo
        sorted_by_sales = sorted(products_data, key=lambda x: x.get('total_sold', 0), reverse=True)[:10]
        print(f"\n🏆 TOP 10 PRODUCTOS MÁS VENDIDOS (en el archivo):")
        for i, product in enumerate(sorted_by_sales, 1):
            print(f"   {i}. {product['title']}: {product.get('total_sold', 0)} unidades")
        
        print(f"\n🎯 SISTEMA LISTO")
        print(f"   El archivo ahora incluye:")
        print(f"   ✅ Datos de ventas reales de los últimos 90 días")
        print(f"   ✅ Colecciones para filtrado por tipo de piel")
        print(f"   ✅ Rankings basados en ventas históricas")
        print(f"   ✅ Disponibilidad basada solo en stock")
        
        return products_data
        
    except Exception as e:
        print(f"❌ Error en sincronización: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    print("=== SHOPIFY SYNC CON VENTAS HISTÓRICAS ===")
    result = sync_products_with_collections()
    
    if result:
        print(f"\n🎉 SINCRONIZACIÓN EXITOSA")
        print(f"Puedes ejecutar app.py para usar el recomendador con datos de ventas reales")
    else:
        print(f"\n❌ SINCRONIZACIÓN FALLÓ")
        print(f"Revisa los errores arriba y verifica tu configuración")