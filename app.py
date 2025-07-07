from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import pandas as pd
import numpy as np
from datetime import datetime
import os
import json
import threading
import time

app = Flask(__name__)
CORS(app, origins=['*'])  # Permitir requests desde Shopify

# Configuración global
PRODUCTS_FILE = 'shopify_products.json'
UPDATE_INTERVAL = 3600  # Actualizar cada hora
last_update = None
products_df = pd.DataFrame()

# Thread para actualización automática
update_thread = None

def load_products_from_file():
    """Carga productos desde el archivo JSON generado por shopify_sync.py"""
    global products_df, last_update
    
    print(f"=== CARGANDO PRODUCTOS ===")
    print(f"Buscando archivo: {PRODUCTS_FILE}")
    print(f"Directorio actual: {os.getcwd()}")
    print(f"Archivos disponibles: {os.listdir('.')}")
    
    try:
        if os.path.exists(PRODUCTS_FILE):
            print(f"Archivo {PRODUCTS_FILE} encontrado!")
            with open(PRODUCTS_FILE, 'r') as f:
                products_data = json.load(f)
            
            print(f"Datos JSON cargados: {len(products_data)} productos")
            products_df = pd.DataFrame(products_data)
            
            # Asegurar que las columnas necesarias existen
            required_columns = ['product_id', 'variant_id', 'title', 'sku', 'price', 
                               'stock', 'product_type', 'vendor', 'tags', 'handle']
            
            for col in required_columns:
                if col not in products_df.columns:
                    products_df[col] = ''
            
            # Convertir tipos de datos
            products_df['price'] = pd.to_numeric(products_df['price'], errors='coerce').fillna(0)
            products_df['stock'] = pd.to_numeric(products_df['stock'], errors='coerce').fillna(0).astype(int)
            products_df['available'] = products_df['stock'] > 0
            
            # Procesar tags (si vienen como string JSON)
            if 'tags' in products_df.columns:
                products_df['tags_str'] = products_df['tags'].apply(
                    lambda x: ', '.join(x) if isinstance(x, list) else str(x)
                )
            else:
                products_df['tags_str'] = ''
            
            # Mapear campos para compatibilidad con tu código actual
            products_df['name'] = products_df['title']
            products_df['precio'] = products_df['price']
            products_df['tipo_producto'] = products_df['product_type']
            products_df['etiquetas_shopify'] = products_df['tags_str']
            products_df['url'] = products_df['handle'].apply(lambda x: f"/products/{x}" if x else '')
            products_df['imagen_url'] = products_df.get('image_url', '')
            
            # Crear campo tipo_piel basado en tags o tipo de producto
            products_df['tipo_piel'] = products_df.apply(categorize_skin_type, axis=1)
            
            # Calcular popularidad simple (basada en stock)
            max_stock = products_df['stock'].max() if len(products_df) > 0 else 1
            products_df['prob_popularidad'] = products_df['stock'] / max(max_stock, 1)
            
            last_update = datetime.now()
            print(f"✅ Productos cargados exitosamente: {len(products_df)} items")
            return True
        else:
            print(f"❌ Archivo {PRODUCTS_FILE} NO encontrado")
            return False
            
    except Exception as e:
        print(f"❌ Error cargando productos: {e}")
        import traceback
        traceback.print_exc()
        return False

def categorize_skin_type(row):
    """Categoriza tipo de piel basado en tags y tipo de producto"""
    tags_lower = str(row.get('tags_str', '')).lower()
    product_type_lower = str(row.get('product_type', '')).lower()
    
    skin_types = []
    
    # Buscar indicadores en tags y tipo de producto
    combined_text = f"{tags_lower} {product_type_lower}"
    
    if any(word in combined_text for word in ['grasa', 'oily', 'acne', 'matificante']):
        skin_types.append('grasa')
    if any(word in combined_text for word in ['seca', 'dry', 'hidratante', 'nutritiva']):
        skin_types.append('seca')
    if any(word in combined_text for word in ['mixta', 'combination', 'balance']):
        skin_types.append('mixta')
    if any(word in combined_text for word in ['sensible', 'sensitive', 'suave', 'gentle']):
        skin_types.append('sensible')
    if any(word in combined_text for word in ['normal', 'todo tipo', 'all skin']):
        skin_types.append('normal')
    
    # Si no se encontró ningún tipo específico, asumir que es para todo tipo de piel
    if not skin_types:
        skin_types = ['normal', 'grasa', 'seca', 'mixta', 'sensible']
    
    return ', '.join(skin_types)

def categorize_product_step(row):
    """Categoriza el paso de la rutina basado en el tipo de producto"""
    product_type = str(row.get('product_type', '')).lower()
    title = str(row.get('title', '')).lower()
    tags = str(row.get('tags_str', '')).lower()
    
    # Combinar toda la información
    combined = f"{product_type} {title} {tags}"
    
    # Mapeo de palabras clave a pasos de rutina
    step_mapping = {
        'limpiador en espuma': ['foam', 'espuma', 'cleanser foam', 'limpiador espuma'],
        'limpiador oleoso': ['oil cleanser', 'aceite limpiador', 'cleansing oil'],
        'tónico': ['toner', 'tonico', 'tónico'],
        'serum': ['serum', 'sérum', 'essence', 'ampoule'],
        'hidratante': ['moisturizer', 'cream', 'crema', 'hidratante', 'lotion'],
        'protector solar': ['sunscreen', 'spf', 'protector solar', 'bloqueador']
    }
    
    for step, keywords in step_mapping.items():
        if any(keyword in combined for keyword in keywords):
            return step
    
    return 'otros'

def validate_user_responses(respuestas_usuario):
    """Valida la estructura y contenido de las respuestas del usuario"""
    if not isinstance(respuestas_usuario, dict):
        return False, "Los datos deben ser un objeto JSON válido"

    # Validar campos requeridos
    required_fields = ["tipo_piel", "preocupaciones", "vegano"]
    missing_fields = [field for field in required_fields if field not in respuestas_usuario]

    if missing_fields:
        return False, f"Campos faltantes: {', '.join(missing_fields)}"

    # Validar tipos de datos
    if not isinstance(respuestas_usuario.get("tipo_piel"), str):
        return False, "El campo 'tipo_piel' debe ser una cadena de texto"

    if not isinstance(respuestas_usuario.get("preocupaciones"), list):
        return False, "El campo 'preocupaciones' debe ser una lista"

    if not isinstance(respuestas_usuario.get("vegano"), bool):
        return False, "El campo 'vegano' debe ser un valor booleano"

    return True, "Datos válidos"

def apply_base_filters(df, tipo_piel, preocupaciones, vegano):
    """Aplica filtros base de forma optimizada"""
    try:
        filtered_df = df.copy()
        
        # Solo filtrar productos disponibles
        filtered_df = filtered_df[filtered_df['available'] == True]
        
        # Filtro vegano
        if vegano:
            mask_vegano = filtered_df["etiquetas_shopify"].str.contains("vegano|vegan", case=False, na=False)
            filtered_df = filtered_df[mask_vegano]
        
        # Filtro tipo de piel
        if tipo_piel:
            mask_tipo_piel = filtered_df["tipo_piel"].str.contains(tipo_piel, case=False, na=False)
            filtered_df = filtered_df[mask_tipo_piel]
        
        return filtered_df, None
    except Exception as e:
        return None, f"Error al aplicar filtros base: {str(e)}"

def filter_products_by_step(base_filtered, paso, preocupaciones):
    """Filtra productos por paso específico con lógica de fallback"""
    try:
        # Primero categorizar productos por paso
        base_filtered['step_category'] = base_filtered.apply(categorize_product_step, axis=1)
        
        # Filtrar por paso
        filtered_df = base_filtered[base_filtered['step_category'] == paso].copy()
        
        # Si hay productos, aplicar filtros de preocupaciones
        if len(filtered_df) > 0 and preocupaciones:
            # Intentar con todas las preocupaciones
            temp_filtered = filtered_df.copy()
            for preocupacion in preocupaciones:
                mask = temp_filtered["etiquetas_shopify"].str.contains(preocupacion, case=False, na=False)
                if mask.any():
                    temp_filtered = temp_filtered[mask]
            
            # Si quedan productos después del filtro, usar esos
            if len(temp_filtered) >= 2:
                filtered_df = temp_filtered
        
        # Ordenar por popularidad
        filtered_df = filtered_df.sort_values(by="prob_popularidad", ascending=False)
        
        return filtered_df, None
        
    except Exception as e:
        return None, f"Error al filtrar productos para paso '{paso}': {str(e)}"

def create_product_option(producto, paso):
    """Crea un objeto de opción de producto de forma segura"""
    try:
        return {
            "paso": paso.replace('_', ' ').title(),
            "nombre": str(producto.get("name", "Producto sin nombre")),
            "precio": float(producto.get("precio", 0)),
            "url": str(producto.get("url", "")),
            "imagen_url": str(producto.get("imagen_url", "")),
            "product_id": str(producto.get("product_id", ""))
        }
    except Exception as e:
        return {
            "paso": paso.replace('_', ' ').title(),
            "nombre": "Error al cargar producto",
            "precio": 0,
            "url": "",
            "imagen_url": "",
            "product_id": "",
            "error": str(e)
        }

def get_recommendations(respuestas_usuario):
    """Función principal optimizada para generar recomendaciones"""
    try:
        # Validar entrada
        is_valid, validation_message = validate_user_responses(respuestas_usuario)
        if not is_valid:
            return None, f"Error de validación: {validation_message}"
        
        # Extraer datos del usuario
        tipo_piel = respuestas_usuario.get("tipo_piel", "").lower().strip()
        preocupaciones = [p.lower().strip() for p in respuestas_usuario.get("preocupaciones", []) if p.strip()]
        vegano = respuestas_usuario.get("vegano", False)
        
        # Aplicar filtros base
        base_filtrada, filter_error = apply_base_filters(products_df, tipo_piel, preocupaciones, vegano)
        if filter_error:
            return None, filter_error
        
        # Verificar que hay productos después del filtrado
        if base_filtrada.empty:
            return None, "No se encontraron productos que coincidan con los criterios especificados"
        
        # Definir rutinas
        rutinas = {
            "Rutina Básica": ["limpiador en espuma", "hidratante", "protector solar"],
            "Rutina Intermedia": ["limpiador en espuma", "tónico", "serum", "hidratante", "protector solar"],
            "Rutina Completa": ["limpiador oleoso", "limpiador en espuma", "tónico", "serum", "hidratante", "protector solar"],
        }
        
        recomendaciones_finales = {}
        
        # Procesar cada rutina
        for nombre_rutina, pasos_en_rutina in rutinas.items():
            opciones_rutina_1 = []
            opciones_rutina_2 = []
            todos_los_pasos_tienen_opciones = True
            
            for paso in pasos_en_rutina:
                # Filtrar productos por paso
                match, step_error = filter_products_by_step(base_filtrada, paso, preocupaciones)
                
                if step_error or match.empty:
                    todos_los_pasos_tienen_opciones = False
                    break
                
                if len(match) >= 2:
                    # Crear opciones de productos
                    producto_opcion_1 = match.iloc[0].to_dict()
                    producto_opcion_2 = match.iloc[1].to_dict()
                    
                    opciones_rutina_1.append(create_product_option(producto_opcion_1, paso))
                    opciones_rutina_2.append(create_product_option(producto_opcion_2, paso))
                elif len(match) == 1:
                    # Si solo hay un producto, usarlo para ambas opciones
                    producto = match.iloc[0].to_dict()
                    opciones_rutina_1.append(create_product_option(producto, paso))
                    opciones_rutina_2.append(create_product_option(producto, paso))
                else:
                    todos_los_pasos_tienen_opciones = False
                    break
            
            # Crear resultado para la rutina
            if todos_los_pasos_tienen_opciones and opciones_rutina_1:
                recomendaciones_finales[nombre_rutina] = {
                    "Opción 1": opciones_rutina_1,
                    "Opción 2": opciones_rutina_2
                }
            else:
                recomendaciones_finales[nombre_rutina] = {
                    "No disponible": [{
                        "paso": "Información",
                        "nombre": "No hay suficientes productos disponibles para esta rutina en este momento."
                    }]
                }
        
        return recomendaciones_finales, None
        
    except Exception as e:
        return None, f"Error inesperado en get_recommendations: {str(e)}"

# Endpoint principal
@app.route("/apps/skincare-recommender/recomendar", methods=["POST", "OPTIONS"])
def recomendar_endpoint():
    # Manejar preflight CORS
    if request.method == "OPTIONS":
        response = make_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response
    
    try:
        # Validar que se recibieron datos
        if not request.is_json:
            return jsonify({"error": "Content-Type debe ser application/json"}), 400
        
        respuestas_usuario = request.get_json()
        
        if not respuestas_usuario:
            return jsonify({"error": "No se recibieron datos JSON válidos"}), 400
        
        # Verificar que los productos están cargados
        if products_df.empty:
            load_products_from_file()
            if products_df.empty:
                return jsonify({"error": "No hay productos disponibles en este momento"}), 503
        
        # Generar recomendaciones
        recomendaciones, error = get_recommendations(respuestas_usuario)
        
        if error:
            return jsonify({"error": error}), 400
        
        return jsonify(recomendaciones)
        
    except Exception as e:
        print(f"Error en endpoint: {e}")
        return jsonify({"error": f"Error interno del servidor: {str(e)}"}), 500

@app.route("/health", methods=["GET"])
def health_check():
    """Endpoint de salud para verificar el estado del servicio"""
    return jsonify({
        "status": "healthy",
        "products_loaded": len(products_df),
        "last_update": last_update.isoformat() if last_update else None
    })

@app.route("/api/products/stats", methods=["GET"])
def get_stats():
    """Estadísticas de productos"""
    try:
        return jsonify({
            "total_products": len(products_df),
            "available_products": len(products_df[products_df['available'] == True]) if not products_df.empty else 0,
            "last_update": last_update.isoformat() if last_update else None,
            "product_types": products_df['product_type'].value_counts().to_dict() if not products_df.empty else {}
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def auto_update_products():
    """Función que se ejecuta en un thread separado para actualizar productos"""
    while True:
        try:
            print("Actualizando productos automáticamente...")
            # Ejecutar el script de sincronización
            os.system("python shopify_sync.py")
            # Recargar productos
            load_products_from_file()
        except Exception as e:
            print(f"Error en actualización automática: {e}")
        
        # Esperar hasta la próxima actualización
        time.sleep(UPDATE_INTERVAL)

# ========================================
# IMPORTANTE: CARGAR PRODUCTOS AL INICIO
# ========================================
print("=== INICIANDO APLICACIÓN ===")
print(f"Python: {os.sys.version}")
print(f"Directorio de trabajo: {os.getcwd()}")

# Cargar productos inmediatamente al importar el módulo
load_products_from_file()

# Inicializar thread de actualización solo una vez
if not update_thread or not update_thread.is_alive():
    update_thread = threading.Thread(target=auto_update_products, daemon=True)
    update_thread.start()
    print("✅ Thread de actualización automática iniciado")

# Este bloque solo se ejecuta cuando se ejecuta directamente (no con gunicorn)
if __name__ == "__main__":
    print("=== MODO DESARROLLO ===")
    app.run(host="0.0.0.0", port=5000, debug=False)