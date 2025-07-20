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
CORS(app, origins=['*'])

# Configuración global
PRODUCTS_FILE = 'shopify_products.json'
UPDATE_INTERVAL = 3600
last_update = None
products_df = pd.DataFrame()
update_thread = None

def load_products_from_file():
    """Carga productos desde el archivo JSON con manejo de imágenes"""
    global products_df, last_update
    
    print(f"=== CARGANDO PRODUCTOS ===")
    print(f"Buscando archivo: {PRODUCTS_FILE}")
    print(f"Directorio actual: {os.getcwd()}")
    print(f"Archivos disponibles: {os.listdir('.')}")
    
    try:
        if not os.path.exists(PRODUCTS_FILE):
            print(f"❌ Archivo {PRODUCTS_FILE} NO encontrado")
            return False
            
        print(f"Archivo {PRODUCTS_FILE} encontrado!")
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            products_data = json.load(f)
        
        print(f"Datos JSON cargados: {len(products_data)} productos")
        products_df = pd.DataFrame(products_data)
        
        # Asegurar columnas necesarias
        required_columns = ['product_id', 'variant_id', 'title', 'sku', 'price', 
                           'stock', 'product_type', 'vendor', 'tags', 'handle', 'image_url']
        
        for col in required_columns:
            if col not in products_df.columns:
                products_df[col] = ''
        
        # Procesar datos
        products_df['price'] = pd.to_numeric(products_df['price'], errors='coerce').fillna(0)
        products_df['stock'] = pd.to_numeric(products_df['stock'], errors='coerce').fillna(0).astype(int)
        products_df['available'] = products_df['stock'] > 0
        
        # Procesar tags
        products_df['tags_str'] = products_df['tags'].apply(
            lambda x: ', '.join(x) if isinstance(x, list) else str(x)
        )
        
        # Asegurar colecciones
        if 'collection_handles' not in products_df.columns:
            products_df['collection_handles'] = products_df.apply(lambda x: [], axis=1)
        if 'collection_titles' not in products_df.columns:
            products_df['collection_titles'] = products_df.apply(lambda x: [], axis=1)
        
        # Mapear campos
        products_df['name'] = products_df['title']
        products_df['precio'] = products_df['price']
        products_df['tipo_producto'] = products_df['product_type']
        products_df['etiquetas_shopify'] = products_df['tags_str']
        products_df['url'] = products_df['handle'].apply(lambda x: f"/products/{x}" if x else '')
        products_df['imagen_url'] = products_df['image_url'].fillna('')
        
        # Categorización
        products_df['tipo_piel'] = products_df.apply(categorize_skin_type, axis=1)
        
        # Popularidad
        max_stock = products_df['stock'].max() if len(products_df) > 0 else 1
        products_df['prob_popularidad'] = products_df['stock'] / max(max_stock, 1)
        
        last_update = datetime.now()
        
        # Stats
        products_with_images = products_df[products_df['imagen_url'] != ''].shape[0]
        print(f"✅ Productos cargados: {len(products_df)} items")
        print(f"📷 Productos con imágenes: {products_with_images} de {len(products_df)}")
        
        return True
            
    except Exception as e:
        print(f"❌ Error cargando productos: {e}")
        import traceback
        traceback.print_exc()
        return False

def categorize_skin_type(row):
    """Categoriza tipo de piel basado en tags y tipo de producto"""
    tags_lower = str(row.get('tags_str', '')).lower()
    product_type_lower = str(row.get('product_type', '')).lower()
    title_lower = str(row.get('title', '')).lower()
    
    combined_text = f"{tags_lower} {product_type_lower} {title_lower}"
    
    skin_keywords = {
        'grasa': ['grasa', 'graso', 'oily', 'acne', 'acné', 'matificante', 'oil-control', 'sebum', 'sebo'],
        'seca': ['seca', 'seco', 'dry', 'hidratante', 'nutritiva', 'nutritivo', 'moisturizing', 'nourishing'],
        'mixta': ['mixta', 'mixto', 'combination', 'combo', 'balance', 'equilibrante'],
        'sensible': ['sensible', 'sensitive', 'suave', 'gentle', 'delicada', 'delicado', 'calming', 'soothing'],
        'normal': ['normal', 'todo tipo', 'all skin', 'universal', 'cualquier tipo']
    }
    
    skin_types = []
    for skin_type, keywords in skin_keywords.items():
        if any(keyword in combined_text for keyword in keywords):
            skin_types.append(skin_type)
    
    if not skin_types:
        skin_types = ['normal', 'grasa', 'seca', 'mixta', 'sensible']
    
    return ', '.join(skin_types)

def categorize_product_step(row):
    """Categoriza el paso de la rutina basado en product_type"""
    product_type = str(row.get('product_type', '')).strip()
    tags = str(row.get('tags_str', '')).lower()
    title = str(row.get('title', '')).lower()
    
    # Productos a ignorar
    if product_type in ['Contorno de Ojos']:
        return 'otros'
    
    # Mapeo directo
    product_type_mapping = {
        'Hidratante': 'hidratante',
        'Serum': 'serum',
        'Serum Exfoliante': 'serum',
        'Tónico': 'tónico',
        'Tónico Exfoliante': 'tónico',
        'Protector Solar': 'protector solar',
        'Limpiador Oleoso': 'limpiador oleoso',
        'Limpiador en Espuma': 'limpiador en espuma',
        'Esencia': 'tónico',
        'Exfoliante': 'serum'
    }
    
    if product_type in product_type_mapping:
        return product_type_mapping[product_type]
    
    # Fallback por tags
    tag_mapping = {
        'limpiador oleoso': ['aceite limpiador', 'oil cleanser', 'cleansing oil'],
        'limpiador en espuma': ['limpiador espuma', 'foam cleanser', 'gel limpiador'],
        'tónico': ['tonico', 'tónico', 'toner', 'essence', 'esencia'],
        'serum': ['serum', 'sérum', 'suero', 'ampoule'],
        'hidratante': ['hidratante', 'moisturizer', 'crema hidratante'],
        'protector solar': ['protector solar', 'sunscreen', 'spf']
    }
    
    # Ignorar contorno de ojos
    eye_keywords = ['contorno', 'eye cream', 'under eye', 'ojos', 'ojeras']
    if any(keyword in tags or keyword in title for keyword in eye_keywords):
        return 'otros'
    
    for step, keywords in tag_mapping.items():
        for keyword in keywords:
            if keyword in tags:
                return step
    
    return 'otros'

def get_skin_type_collection_mapping():
    """Mapeo de tipos de piel a handles de colecciones"""
    return {
        'grasa': ['piel-grasa', 'acne', 'oily-skin', 'grasa'],
        'seca': ['piel-seca', 'dry-skin', 'hidratacion', 'seca'],
        'mixta': ['piel-mixta', 'combination-skin', 'mixta'],
        'sensible': ['piel-sensible', 'sensitive-skin', 'calming', 'sensible'],
        'normal': ['piel-normal', 'todo-tipo-piel', 'all-skin-types', 'normal']
    }

def filter_by_skin_type_collection(df, tipo_piel):
    """Filtrar por colección según tipo de piel"""
    if not tipo_piel:
        return df
    
    collection_mapping = get_skin_type_collection_mapping()
    target_collections = collection_mapping.get(tipo_piel.lower(), [])
    
    filtered_products = []
    for _, product in df.iterrows():
        product_collections = product.get('collection_handles', [])
        is_in_skin_collection = any(target_col in product_collections for target_col in target_collections)
        
        if is_in_skin_collection:
            product_dict = product.to_dict()
            product_dict['matched_skin_collections'] = [col for col in target_collections if col in product_collections]
            filtered_products.append(product_dict)
    
    if not filtered_products:
        return df
    
    return pd.DataFrame(filtered_products)

def filter_by_skin_concerns_in_tags(df, preocupaciones):
    """Filtrar por preocupaciones en etiquetas"""
    if not preocupaciones:
        return df
    
    concern_tag_mapping = {
        'acne': ['grasa', 'sebo', 'acne', 'acné', 'comedones', 'espinillas'],
        'manchas': ['manchas', 'pigmentación', 'pigmentacion', 'hiperpigmentación'],
        'arrugas': ['arrugas', 'antiedad', 'anti-edad', 'antienvejecimiento'],
        'poros': ['poros dilatados', 'poros', 'minimizador poros'],
        'hidratacion': ['hidratación', 'hidratacion', 'deshidratación'],
        'sensibilidad': ['sensible', 'rojeces', 'irritación', 'calmante']
    }
    
    target_tags = []
    for concern in preocupaciones:
        if concern.lower() in concern_tag_mapping:
            target_tags.extend(concern_tag_mapping[concern.lower()])
    
    target_tags = list(set(target_tags))
    concern_products = []
    
    for _, product in df.iterrows():
        product_tags = str(product.get('tags_str', '')).lower()
        matched_tags = [tag for tag in target_tags if tag in product_tags]
        
        if matched_tags:
            product_dict = product.to_dict()
            product_dict['matched_concern_tags'] = matched_tags
            product_dict['concern_score'] = len(matched_tags)
            concern_products.append(product_dict)
    
    if not concern_products:
        return df
    
    return pd.DataFrame(concern_products)

def rank_by_sales_probability_and_stock(df):
    """Ordenar por probabilidad de venta y stock"""
    if df.empty:
        return df
    
    def calculate_ranking_score(row):
        stock = int(row.get('stock', 0))
        price = float(row.get('price', 0))
        available = row.get('available', False)
        concern_score = row.get('concern_score', 0)
        
        # Stock score
        if stock > 100: stock_score = 1.0
        elif stock > 50: stock_score = 0.9
        elif stock > 20: stock_score = 0.7
        elif stock > 10: stock_score = 0.5
        elif stock > 0: stock_score = 0.3
        else: stock_score = 0.0
        
        # Price score
        if 15000 <= price <= 45000: price_score = 1.0
        elif 10000 <= price <= 60000: price_score = 0.8
        elif 5000 <= price <= 80000: price_score = 0.6
        else: price_score = 0.4
        
        availability_score = 1.0 if available else 0.0
        concern_bonus = min(concern_score * 0.1, 0.2)
        
        final_score = (
            stock_score * 0.5 +
            price_score * 0.2 +
            availability_score * 0.2 +
            concern_bonus * 0.1
        )
        
        return final_score if stock > 0 else final_score * 0.1
    
    df['final_ranking_score'] = df.apply(calculate_ranking_score, axis=1)
    df['has_stock'] = df['stock'] > 0
    
    sort_columns = ['has_stock']
    sort_ascending = [False]
    
    if 'concern_score' in df.columns:
        sort_columns.append('concern_score')
        sort_ascending.append(False)
    
    sort_columns.append('final_ranking_score')
    sort_ascending.append(False)
    
    return df.sort_values(by=sort_columns, ascending=sort_ascending)

def apply_complete_filtering_pipeline(df, tipo_piel, preocupaciones):
    """Pipeline completo de filtrado"""
    step1_filtered = filter_by_skin_type_collection(df, tipo_piel)
    step2_filtered = filter_by_skin_concerns_in_tags(step1_filtered, preocupaciones)
    final_ranked = rank_by_sales_probability_and_stock(step2_filtered)
    return final_ranked, None

def filter_products_by_step(base_filtered, paso, preocupaciones, tipo_piel):
    """Filtra productos por paso específico"""
    try:
        base_filtered['step_category'] = base_filtered.apply(categorize_product_step, axis=1)
        step_filtered = base_filtered[base_filtered['step_category'] == paso].copy()
        
        if len(step_filtered) == 0:
            return step_filtered, None
        
        final_filtered, error = apply_complete_filtering_pipeline(step_filtered, tipo_piel, preocupaciones)
        return final_filtered, error
        
    except Exception as e:
        return None, f"Error al filtrar productos para paso '{paso}': {str(e)}"

def validate_user_responses(respuestas_usuario):
    """Valida la estructura y contenido de las respuestas del usuario"""
    if not isinstance(respuestas_usuario, dict):
        return False, "Los datos deben ser un objeto JSON válido"

    required_fields = ["tipo_piel", "preocupaciones", "vegano"]
    missing_fields = [field for field in required_fields if field not in respuestas_usuario]

    if missing_fields:
        return False, f"Campos faltantes: {', '.join(missing_fields)}"

    if not isinstance(respuestas_usuario.get("tipo_piel"), str):
        return False, "El campo 'tipo_piel' debe ser una cadena de texto"

    if not isinstance(respuestas_usuario.get("preocupaciones"), list):
        return False, "El campo 'preocupaciones' debe ser una lista"

    if not isinstance(respuestas_usuario.get("vegano"), bool):
        return False, "El campo 'vegano' debe ser un valor booleano"

    return True, "Datos válidos"

def create_product_option(producto, paso):
    """Crea un objeto de opción de producto con imagen incluida"""
    try:
        imagen_url = str(producto.get("imagen_url", ""))
        if imagen_url in ['nan', 'None', 'null']:
            imagen_url = ""
        
        return {
            "paso": paso.replace('_', ' ').title(),
            "nombre": str(producto.get("name", "Producto sin nombre")),
            "precio": float(producto.get("precio", 0)),
            "url": str(producto.get("url", "")),
            "imagen_url": imagen_url,
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
    """Función principal para generar recomendaciones"""
    try:
        is_valid, validation_message = validate_user_responses(respuestas_usuario)
        if not is_valid:
            return None, f"Error de validación: {validation_message}"
        
        tipo_piel = respuestas_usuario.get("tipo_piel", "").lower().strip()
        preocupaciones = [p.lower().strip() for p in respuestas_usuario.get("preocupaciones", []) if p.strip()]
        vegano = respuestas_usuario.get("vegano", False)
        
        base_filtrada = products_df[products_df['available'] == True].copy()
        
        if vegano:
            mask_vegano = base_filtrada["etiquetas_shopify"].str.contains("vegano|vegan", case=False, na=False)
            base_filtrada = base_filtrada[mask_vegano]
        
        if base_filtrada.empty:
            return None, "No se encontraron productos que coincidan con los criterios especificados"
        
        rutinas = {
            "Rutina Básica": ["limpiador en espuma", "hidratante", "protector solar"],
            "Rutina Intermedia": ["limpiador en espuma", "tónico", "serum", "hidratante", "protector solar"],
            "Rutina Completa": ["limpiador oleoso", "limpiador en espuma", "tónico", "serum", "hidratante", "protector solar"],
        }
        
        recomendaciones_finales = {}
        
        for nombre_rutina, pasos_en_rutina in rutinas.items():
            opciones_rutina_1 = []
            opciones_rutina_2 = []
            todos_los_pasos_tienen_opciones = True
            
            for paso in pasos_en_rutina:
                match, step_error = filter_products_by_step(base_filtrada, paso, preocupaciones, tipo_piel)
                
                if step_error or match.empty:
                    todos_los_pasos_tienen_opciones = False
                    break
                
                if len(match) >= 2:
                    producto_opcion_1 = match.iloc[0].to_dict()
                    producto_opcion_2 = match.iloc[1].to_dict()
                    
                    opciones_rutina_1.append(create_product_option(producto_opcion_1, paso))
                    opciones_rutina_2.append(create_product_option(producto_opcion_2, paso))
                elif len(match) == 1:
                    producto = match.iloc[0].to_dict()
                    opciones_rutina_1.append(create_product_option(producto, paso))
                    opciones_rutina_2.append(create_product_option(producto, paso))
                else:
                    todos_los_pasos_tienen_opciones = False
                    break
            
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

# ENDPOINTS
@app.route("/apps/skincare-recommender/recomendar", methods=["POST", "OPTIONS"])
def recomendar_endpoint():
    if request.method == "OPTIONS":
        response = make_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response
    
    try:
        if not request.is_json:
            return jsonify({"error": "Content-Type debe ser application/json"}), 400
        
        respuestas_usuario = request.get_json()
        
        if not respuestas_usuario:
            return jsonify({"error": "No se recibieron datos JSON válidos"}), 400
        
        if products_df.empty:
            load_products_from_file()
            if products_df.empty:
                return jsonify({"error": "No hay productos disponibles en este momento"}), 503
        
        recomendaciones, error = get_recommendations(respuestas_usuario)
        
        if error:
            return jsonify({"error": error}), 400
        
        return jsonify(recomendaciones)
        
    except Exception as e:
        return jsonify({"error": f"Error interno del servidor: {str(e)}"}), 500

@app.route("/health", methods=["GET"])
def health_check():
    """Endpoint de salud"""
    return jsonify({
        "status": "healthy",
        "products_loaded": len(products_df),
        "last_update": last_update.isoformat() if last_update else None
    })

@app.route("/api/debug/images", methods=["GET"])
def debug_images():
    """Debug específico para verificar las imágenes"""
    try:
        if products_df.empty:
            return jsonify({"error": "No hay productos cargados"}), 404
        
        total_products = len(products_df)
        with_images = products_df[products_df['imagen_url'] != ''].shape[0]
        without_images = total_products - with_images
        
        # Ejemplos
        products_with_images = products_df[products_df['imagen_url'] != ''].head(5)
        examples_with_images = products_with_images[['title', 'imagen_url', 'product_type']].to_dict('records')
        
        products_without_images = products_df[products_df['imagen_url'] == ''].head(5)
        examples_without_images = products_without_images[['title', 'imagen_url', 'product_type']].to_dict('records')
        
        return jsonify({
            "total_products": total_products,
            "products_with_images": with_images,
            "products_without_images": without_images,
            "percentage_with_images": round((with_images / total_products * 100), 2) if total_products > 0 else 0,
            "examples_with_images": examples_with_images,
            "examples_without_images": examples_without_images,
            "sample_image_urls": products_df[products_df['imagen_url'] != '']['imagen_url'].head(3).tolist()
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def auto_update_products():
    """Actualización automática de productos"""
    while True:
        try:
            print("Actualizando productos automáticamente...")
            os.system("python shopify_sync.py")
            load_products_from_file()
        except Exception as e:
            print(f"Error en actualización automática: {e}")
        
        time.sleep(UPDATE_INTERVAL)

# INICIALIZACIÓN
print("=== INICIANDO APLICACIÓN ===")
print(f"Directorio de trabajo: {os.getcwd()}")

load_products_from_file()

# Comentar temporalmente la actualización automática
# if not update_thread or not update_thread.is_alive():
#     update_thread = threading.Thread(target=auto_update_products, daemon=True)
#     update_thread.start()
#     print("✅ Thread de actualización automática iniciado")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"=== INICIANDO EN PUERTO {port} ===")
    print(f"Productos cargados: {len(products_df)}")
    app.run(host="0.0.0.0", port=port, debug=False)