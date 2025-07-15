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
            with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
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
            
            # Asegurar que existen las columnas de colecciones (para el nuevo sistema)
            if 'collection_handles' not in products_df.columns:
                products_df['collection_handles'] = products_df.apply(lambda x: [], axis=1)
            if 'collection_titles' not in products_df.columns:
                products_df['collection_titles'] = products_df.apply(lambda x: [], axis=1)
            
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
    """Categoriza tipo de piel basado en tags y tipo de producto - MEJORADO"""
    tags_lower = str(row.get('tags_str', '')).lower()
    product_type_lower = str(row.get('product_type', '')).lower()
    title_lower = str(row.get('title', '')).lower()
    
    skin_types = []
    
    # Buscar indicadores en tags, tipo de producto y título
    combined_text = f"{tags_lower} {product_type_lower} {title_lower}"
    
    # Palabras clave más específicas y en español/inglés
    skin_keywords = {
        'grasa': ['grasa', 'graso', 'oily', 'acne', 'acné', 'matificante', 'oil-control', 'sebum', 'sebo'],
        'seca': ['seca', 'seco', 'dry', 'hidratante', 'nutritiva', 'nutritivo', 'moisturizing', 'nourishing'],
        'mixta': ['mixta', 'mixto', 'combination', 'combo', 'balance', 'equilibrante'],
        'sensible': ['sensible', 'sensitive', 'suave', 'gentle', 'delicada', 'delicado', 'calming', 'soothing'],
        'normal': ['normal', 'todo tipo', 'all skin', 'universal', 'cualquier tipo']
    }
    
    for skin_type, keywords in skin_keywords.items():
        if any(keyword in combined_text for keyword in keywords):
            skin_types.append(skin_type)
    
    # Si no se encontró ningún tipo específico, asumir que es para todo tipo de piel
    if not skin_types:
        skin_types = ['normal', 'grasa', 'seca', 'mixta', 'sensible']
    
    return ', '.join(skin_types)

def categorize_product_step(row):
    """Categoriza el paso de la rutina basado en product_type de Shopify"""
    product_type = str(row.get('product_type', '')).strip()
    tags = str(row.get('tags_str', '')).lower()
    title = str(row.get('title', '')).lower()
    
    # PRODUCTOS A IGNORAR - No incluir en rutinas básicas
    ignored_types = ['Contorno de Ojos']
    
    if product_type in ignored_types:
        return 'otros'
    
    # Mapeo DIRECTO basado en tus product_type existentes
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
    
    # Buscar coincidencia exacta con product_type
    if product_type in product_type_mapping:
        return product_type_mapping[product_type]
    
    # Si no hay coincidencia exacta, buscar en etiquetas como fallback
    tag_mapping = {
        'limpiador oleoso': ['aceite limpiador', 'oil cleanser', 'cleansing oil', 'primera limpieza'],
        'limpiador en espuma': ['limpiador espuma', 'foam cleanser', 'gel limpiador', 'segunda limpieza'],
        'tónico': ['tonico', 'tónico', 'toner', 'essence', 'esencia'],
        'serum': ['serum', 'sérum', 'suero', 'ampoule', 'ampolla'],
        'hidratante': ['hidratante', 'moisturizer', 'crema hidratante'],
        'protector solar': ['protector solar', 'sunscreen', 'bloqueador', 'spf']
    }
    
    # Verificar si contiene palabras de contorno de ojos en tags/título para ignorar
    eye_keywords = ['contorno', 'eye cream', 'under eye', 'ojos', 'ojeras']
    if any(keyword in tags or keyword in title for keyword in eye_keywords):
        return 'otros'
    
    for step, keywords in tag_mapping.items():
        for keyword in keywords:
            if keyword in tags:
                return step
    
    return 'otros'

# ========================================
# NUEVO SISTEMA DE PIPELINE
# ========================================

def get_skin_type_collection_mapping():
    """Mapeo de tipos de piel a handles de colecciones en Shopify"""
    return {
        'grasa': ['piel-grasa', 'acne', 'oily-skin', 'grasa'],
        'seca': ['piel-seca', 'dry-skin', 'hidratacion', 'seca'],
        'mixta': ['piel-mixta', 'combination-skin', 'mixta'],
        'sensible': ['piel-sensible', 'sensitive-skin', 'calming', 'sensible'],
        'normal': ['piel-normal', 'todo-tipo-piel', 'all-skin-types', 'normal']
    }

def filter_by_skin_type_collection(df, tipo_piel):
    """PASO 1: Filtrar por colección según tipo de piel"""
    if not tipo_piel:
        return df
    
    print(f"=== PASO 1: FILTRANDO POR COLECCIÓN DE TIPO DE PIEL ===")
    print(f"Tipo de piel: {tipo_piel}")
    
    # Obtener colecciones correspondientes al tipo de piel
    collection_mapping = get_skin_type_collection_mapping()
    target_collections = collection_mapping.get(tipo_piel.lower(), [])
    
    print(f"Colecciones objetivo: {target_collections}")
    
    # Filtrar productos que estén en alguna de las colecciones target
    filtered_products = []
    
    for _, product in df.iterrows():
        product_collections = product.get('collection_handles', [])
        
        # Verificar si el producto está en alguna colección del tipo de piel
        is_in_skin_collection = any(
            target_col in product_collections 
            for target_col in target_collections
        )
        
        if is_in_skin_collection:
            matched_collections = [col for col in target_collections if col in product_collections]
            product_dict = product.to_dict()
            product_dict['matched_skin_collections'] = matched_collections
            filtered_products.append(product_dict)
            
            print(f"✅ {product.get('title', '')} → Colecciones: {matched_collections}")
    
    if not filtered_products:
        print(f"❌ No se encontraron productos en colecciones de {tipo_piel}")
        print("📋 Colecciones disponibles en productos:")
        all_collections = set()
        for _, product in df.iterrows():
            all_collections.update(product.get('collection_handles', []))
        print(f"   {sorted(list(all_collections))}")
        
        # Fallback: devolver todos los productos
        print("🔄 Usando fallback: todos los productos")
        return df
    
    result_df = pd.DataFrame(filtered_products)
    print(f"✅ PASO 1 COMPLETADO: {len(result_df)} productos filtrados por tipo de piel")
    
    return result_df

def filter_by_skin_concerns_in_tags(df, preocupaciones):
    """PASO 2: Filtrar por preocupaciones en etiquetas"""
    if not preocupaciones:
        return df
    
    print(f"=== PASO 2: FILTRANDO POR PREOCUPACIONES EN ETIQUETAS ===")
    print(f"Preocupaciones: {preocupaciones}")
    
    # Mapeo de preocupaciones a etiquetas específicas (basado en TUS etiquetas)
    concern_tag_mapping = {
        'acne': ['grasa', 'sebo', 'acne', 'acné', 'comedones', 'espinillas'],
        'manchas': ['manchas', 'pigmentación', 'pigmentacion', 'hiperpigmentación'],
        'arrugas': ['arrugas', 'antiedad', 'anti-edad', 'antienvejecimiento'],
        'poros': ['poros dilatados', 'poros', 'minimizador poros'],
        'hidratacion': ['hidratación', 'hidratacion', 'deshidratación'],
        'sensibilidad': ['sensible', 'rojeces', 'irritación', 'calmante']
    }
    
    # Crear lista de etiquetas a buscar
    target_tags = []
    for concern in preocupaciones:
        if concern.lower() in concern_tag_mapping:
            target_tags.extend(concern_tag_mapping[concern.lower()])
    
    target_tags = list(set(target_tags))  # Eliminar duplicados
    print(f"Etiquetas objetivo: {target_tags}")
    
    # Filtrar productos que tengan alguna de las etiquetas objetivo
    concern_products = []
    
    for _, product in df.iterrows():
        product_tags = str(product.get('tags_str', '')).lower()
        
        # Buscar matches en etiquetas
        matched_tags = []
        concern_score = 0
        
        for tag in target_tags:
            if tag in product_tags:
                matched_tags.append(tag)
                concern_score += 1
        
        if matched_tags:
            product_dict = product.to_dict()
            product_dict['matched_concern_tags'] = matched_tags
            product_dict['concern_score'] = concern_score
            concern_products.append(product_dict)
            
            print(f"✅ {product.get('title', '')} → Tags: {matched_tags} (Score: {concern_score})")
    
    if not concern_products:
        print(f"❌ No se encontraron productos con etiquetas de preocupaciones específicas")
        
        # Mostrar etiquetas disponibles para debug
        print("📋 Etiquetas disponibles en productos filtrados:")
        available_tags = set()
        for _, product in df.iterrows():
            if product.get('tags_str'):
                available_tags.update(str(product['tags_str']).lower().split(', '))
        print(f"   {sorted(list(available_tags))[:10]}...")  # Mostrar primeras 10
        
        # Fallback: devolver productos sin filtro de preocupaciones
        print("🔄 Usando fallback: productos sin filtro de preocupaciones")
        return df
    
    result_df = pd.DataFrame(concern_products)
    print(f"✅ PASO 2 COMPLETADO: {len(result_df)} productos con preocupaciones específicas")
    
    return result_df

def rank_by_sales_probability_and_stock(df):
    """PASO 3: Ordenar por probabilidad de venta y stock"""
    if df.empty:
        return df
    
    print(f"=== PASO 3: RANKING POR PROBABILIDAD DE VENTA Y STOCK ===")
    
    def calculate_ranking_score(row):
        stock = int(row.get('stock', 0))
        price = float(row.get('price', 0))
        available = row.get('available', False)
        concern_score = row.get('concern_score', 0)
        
        # Stock score (más peso porque es prioritario)
        if stock > 100:
            stock_score = 1.0
        elif stock > 50:
            stock_score = 0.9
        elif stock > 20:
            stock_score = 0.7
        elif stock > 10:
            stock_score = 0.5
        elif stock > 0:
            stock_score = 0.3
        else:
            stock_score = 0.0
        
        # Price score (productos en rango medio son más populares)
        if 15000 <= price <= 45000:
            price_score = 1.0
        elif 10000 <= price <= 60000:
            price_score = 0.8
        elif 5000 <= price <= 80000:
            price_score = 0.6
        else:
            price_score = 0.4
        
        # Availability score
        availability_score = 1.0 if available else 0.0
        
        # Concern score bonus
        concern_bonus = min(concern_score * 0.1, 0.2)  # Max 0.2 bonus
        
        # Score final ponderado
        final_score = (
            stock_score * 0.5 +          # 50% peso al stock
            price_score * 0.2 +          # 20% peso al precio
            availability_score * 0.2 +   # 20% peso a disponibilidad
            concern_bonus * 0.1          # 10% peso a preocupaciones específicas
        )
        
        # Penalizar productos sin stock
        return final_score if stock > 0 else final_score * 0.1
    
    # Aplicar cálculo de ranking
    df['final_ranking_score'] = df.apply(calculate_ranking_score, axis=1)
    df['has_stock'] = df['stock'] > 0
    
    # Ordenar por: 
    # 1. Productos con stock (prioritario)
    # 2. Score de preocupaciones (si existe)
    # 3. Score final de ranking
    sort_columns = ['has_stock']
    sort_ascending = [False]
    
    if 'concern_score' in df.columns:
        sort_columns.append('concern_score')
        sort_ascending.append(False)
    
    sort_columns.append('final_ranking_score')
    sort_ascending.append(False)
    
    ranked_df = df.sort_values(by=sort_columns, ascending=sort_ascending)
    
    print(f"✅ PASO 3 COMPLETADO: Productos ordenados por probabilidad de venta")
    print("🏆 TOP 3 productos:")
    
    for i, (_, product) in enumerate(ranked_df.head(3).iterrows()):
        stock = product.get('stock', 0)
        score = product.get('final_ranking_score', 0)
        concern_score = product.get('concern_score', 0)
        price = product.get('price', 0)
        print(f"   {i+1}. {product.get('title', '')} (Stock: {stock}, Score: {score:.3f}, Concerns: {concern_score}, Precio: ${price:,.0f})")
    
    return ranked_df

def apply_complete_filtering_pipeline(df, tipo_piel, preocupaciones):
    """Pipeline completo: Colección → Preocupaciones → Ranking"""
    
    print(f"🔄 INICIANDO PIPELINE COMPLETO DE FILTRADO")
    print(f"   Productos iniciales: {len(df)}")
    print(f"   Tipo de piel: {tipo_piel}")
    print(f"   Preocupaciones: {preocupaciones}")
    
    # PASO 1: Filtrar por colección de tipo de piel
    step1_filtered = filter_by_skin_type_collection(df, tipo_piel)
    print(f"   Después de PASO 1: {len(step1_filtered)} productos")
    
    # PASO 2: Filtrar por preocupaciones en etiquetas
    step2_filtered = filter_by_skin_concerns_in_tags(step1_filtered, preocupaciones)
    print(f"   Después de PASO 2: {len(step2_filtered)} productos")
    
    # PASO 3: Ranking por ventas y stock
    final_ranked = rank_by_sales_probability_and_stock(step2_filtered)
    print(f"   Productos finales ordenados: {len(final_ranked)}")
    
    print(f"✅ PIPELINE COMPLETADO")
    
    return final_ranked, None

# ========================================
# MODIFICAR FUNCIONES EXISTENTES
# ========================================

def filter_products_by_step(base_filtered, paso, preocupaciones, tipo_piel):
    """Filtra productos por paso específico usando el NUEVO PIPELINE"""
    try:
        # Primero categorizar productos por paso
        base_filtered['step_category'] = base_filtered.apply(categorize_product_step, axis=1)
        
        print(f"=== FILTRANDO PASO: {paso} ===")
        step_counts = base_filtered['step_category'].value_counts()
        print(f"Productos por categoría: {step_counts.to_dict()}")
        
        # Filtrar por paso
        step_filtered = base_filtered[base_filtered['step_category'] == paso].copy()
        print(f"Productos encontrados para '{paso}': {len(step_filtered)}")
        
        if len(step_filtered) == 0:
            return step_filtered, None
        
        # APLICAR PIPELINE COMPLETO: Colección → Preocupaciones → Ranking
        final_filtered, error = apply_complete_filtering_pipeline(
            step_filtered, 
            tipo_piel, 
            preocupaciones
        )
        
        if error:
            return None, error
        
        print(f"Productos finales después del pipeline: {len(final_filtered)}")
        
        return final_filtered, None
        
    except Exception as e:
        print(f"❌ Error en filtrado: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, f"Error al filtrar productos para paso '{paso}': {str(e)}"

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
        
        print(f"=== PROCESANDO RECOMENDACIONES ===")
        print(f"Tipo de piel: {tipo_piel}")
        print(f"Preocupaciones: {preocupaciones}")
        print(f"Vegano: {vegano}")
        
        # Aplicar SOLO filtros base (disponibilidad y vegano)
        # El filtro por tipo de piel ahora se hace en el pipeline
        base_filtrada = products_df[products_df['available'] == True].copy()
        
        if vegano:
            mask_vegano = base_filtrada["etiquetas_shopify"].str.contains("vegano|vegan", case=False, na=False)
            base_filtrada = base_filtrada[mask_vegano]
        
        # Verificar que hay productos después del filtrado
        if base_filtrada.empty:
            return None, "No se encontraron productos que coincidan con los criterios especificados"
        
        print(f"Productos después de filtros base: {len(base_filtrada)}")
        
        # Definir rutinas EN EL ORDEN CORRECTO
        rutinas = {
            "Rutina Básica": ["limpiador en espuma", "hidratante", "protector solar"],
            "Rutina Intermedia": ["limpiador en espuma", "tónico", "serum", "hidratante", "protector solar"],
            "Rutina Completa": ["limpiador oleoso", "limpiador en espuma", "tónico", "serum", "hidratante", "protector solar"],
        }
        
        recomendaciones_finales = {}
        
        # Procesar cada rutina
        for nombre_rutina, pasos_en_rutina in rutinas.items():
            print(f"\n=== PROCESANDO {nombre_rutina.upper()} ===")
            opciones_rutina_1 = []
            opciones_rutina_2 = []
            todos_los_pasos_tienen_opciones = True
            
            for paso in pasos_en_rutina:
                print(f"\nProcesando paso: {paso}")
                # Filtrar productos por paso usando el NUEVO PIPELINE
                match, step_error = filter_products_by_step(base_filtrada, paso, preocupaciones, tipo_piel)
                
                if step_error or match.empty:
                    print(f"No se encontraron productos para {paso}")
                    todos_los_pasos_tienen_opciones = False
                    break
                
                print(f"Productos encontrados para {paso}: {len(match)}")
                if len(match) > 0:
                    print(f"Primeros productos: {match[['name', 'step_category']].head().to_dict('records')}")
                
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
                print(f"✅ {nombre_rutina} completada con {len(opciones_rutina_1)} pasos")
            else:
                recomendaciones_finales[nombre_rutina] = {
                    "No disponible": [{
                        "paso": "Información",
                        "nombre": "No hay suficientes productos disponibles para esta rutina en este momento."
                    }]
                }
                print(f"❌ {nombre_rutina} no disponible")
        
        return recomendaciones_finales, None
        
    except Exception as e:
        print(f"❌ Error en get_recommendations: {str(e)}")
        import traceback
        traceback.print_exc()
        return None, f"Error inesperado en get_recommendations: {str(e)}"

# ========================================
# MANTENER FUNCIONES EXISTENTES
# ========================================

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
        
        print(f"=== ENDPOINT RECIBIDO ===")
        print(f"Datos recibidos: {respuestas_usuario}")
        
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
        import traceback
        traceback.print_exc()
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

@app.route("/api/products/debug", methods=["GET"])
def debug_products():
    """Endpoint para debug de productos y clasificación"""
    try:
        if products_df.empty:
            return jsonify({"error": "No hay productos cargados"}), 404
        
        # Aplicar categorización
        debug_df = products_df.copy()
        debug_df['step_category'] = debug_df.apply(categorize_product_step, axis=1)
        
        # Estadísticas por categoría de rutina
        step_stats = debug_df['step_category'].value_counts().to_dict()
        
        # Estadísticas por product_type original
        product_type_stats = debug_df['product_type'].value_counts().to_dict()
        
        # Mapeo de product_type a step_category
        type_to_step_mapping = {}
        for product_type in debug_df['product_type'].unique():
            if pd.notna(product_type) and product_type != '':
                step_counts = debug_df[debug_df['product_type'] == product_type]['step_category'].value_counts()
                type_to_step_mapping[product_type] = step_counts.to_dict()
        
        # Ejemplos de productos por categoría de rutina
        examples = {}
        for step in step_stats.keys():
            step_products = debug_df[debug_df['step_category'] == step].head(3)
            examples[step] = step_products[['name', 'product_type', 'step_category']].to_dict('records')
        
        # Productos sin clasificar
        unclassified = debug_df[debug_df['step_category'] == 'otros']
        unclassified_examples = unclassified[['name', 'product_type', 'tags_str']].head(10).to_dict('records')
        
        return jsonify({
            "total_products": len(debug_df),
            "step_statistics": step_stats,
            "product_type_statistics": product_type_stats,
            "type_to_step_mapping": type_to_step_mapping,
            "examples_by_step": examples,
            "unclassified_products": {
                "count": len(unclassified),
                "examples": unclassified_examples
            },
            "current_product_types": {
                "recognized": [
                    "Hidratante", "Serum", "Tónico", "Protector Solar", 
                    "Limpiador Oleoso", "Limpiador en Espuma",
                    "Esencia", "Tónico Exfoliante", "Exfoliante", "Serum Exfoliante"
                ],
                "ignored": [
                    "Contorno de Ojos"
                ],
                "mapping_info": {
                    "Hidratante → hidratante": "Para el paso de hidratación",
                    "Serum → serum": "Para tratamientos específicos",
                    "Tónico → tónico": "Para preparar la piel",
                    "Protector Solar → protector solar": "Para protección UV",
                    "Limpiador Oleoso → limpiador oleoso": "Primera limpieza",
                    "Limpiador en Espuma → limpiador en espuma": "Segunda limpieza",
                    "Esencia → tónico": "Se usa como tónico en la rutina",
                    "Contorno de Ojos → IGNORADO": "Producto muy específico, no incluido en rutinas básicas"
                }
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/debug/collections", methods=["GET"])
def debug_collections():
    """Debug del sistema basado en colecciones - NUEVO ENDPOINT"""
    try:
        if products_df.empty:
            return jsonify({"error": "No hay productos cargados"}), 404
        
        # Analizar colecciones disponibles
        all_collections = set()
        collection_counts = {}
        
        for _, product in products_df.iterrows():
            collections = product.get('collection_handles', [])
            for collection in collections:
                all_collections.add(collection)
                collection_counts[collection] = collection_counts.get(collection, 0) + 1
        
        # Test del pipeline completo
        test_tipo_piel = "grasa"
        test_preocupaciones = ["acne", "poros"]
        
        # Filtrar solo productos de sérums para el test
        test_df = products_df[products_df.apply(categorize_product_step, axis=1) == 'serum'].copy()
        
        if len(test_df) > 0:
            test_result, _ = apply_complete_filtering_pipeline(test_df, test_tipo_piel, test_preocupaciones)
            test_summary = {
                "initial_serums": len(test_df),
                "final_filtered": len(test_result),
                "top_3_products": test_result.head(3)[['title', 'stock', 'final_ranking_score']].to_dict('records') if len(test_result) > 0 else []
            }
        else:
            test_summary = {"error": "No hay sérums para testear"}
        
        return jsonify({
            "total_products": len(products_df),
            "collections_available": sorted(list(all_collections)),
            "collection_counts": collection_counts,
            "skin_type_mapping": get_skin_type_collection_mapping(),
            "pipeline_test": test_summary,
            "pipeline_info": {
                "step_1": "Filtrar por colección de tipo de piel",
                "step_2": "Filtrar por etiquetas de preocupaciones",
                "step_3": "Ranking por probabilidad de venta y stock"
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/products/tags-suggestions", methods=["GET"])
def suggest_tags():
    """Endpoint para sugerir etiquetas basado en nombres de productos"""
    try:
        if products_df.empty:
            return jsonify({"error": "No hay productos cargados"}), 404
        
        suggestions = []
        
        for _, product in products_df.iterrows():
            title = str(product.get('title', '')).lower()
            current_tags = str(product.get('tags_str', '')).lower()
            
            suggested_tags = []
            
            # Analizar título y sugerir etiquetas
            if any(word in title for word in ['oil', 'aceite', 'cleansing oil']):
                if 'aceite limpiador' not in current_tags:
                    suggested_tags.append('aceite limpiador')
            
            if any(word in title for word in ['foam', 'espuma', 'gel']):
                if 'limpiador espuma' not in current_tags:
                    suggested_tags.append('limpiador espuma')
            
            if any(word in title for word in ['toner', 'tonico', 'tónico', 'essence']):
                if 'tonico' not in current_tags:
                    suggested_tags.append('tonico')
            
            if any(word in title for word in ['serum', 'sérum', 'suero', 'ampoule']):
                if 'serum' not in current_tags:
                    suggested_tags.append('serum')
            
            if any(word in title for word in ['moisturizer', 'crema', 'hidratante']):
                if 'hidratante' not in current_tags:
                    suggested_tags.append('hidratante')
            
            if any(word in title for word in ['sunscreen', 'spf', 'protector', 'solar']):
                if 'protector solar' not in current_tags:
                    suggested_tags.append('protector solar')
            
            if suggested_tags:
                suggestions.append({
                    'product_id': product.get('product_id'),
                    'title': product.get('title'),
                    'current_tags': product.get('tags_str'),
                    'suggested_tags': suggested_tags
                })
        
        return jsonify({
            "total_suggestions": len(suggestions),
            "suggestions": suggestions[:20],  # Limitar a 20 para no sobrecargar
            "note": "Estas son sugerencias basadas en el análisis del título del producto"
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