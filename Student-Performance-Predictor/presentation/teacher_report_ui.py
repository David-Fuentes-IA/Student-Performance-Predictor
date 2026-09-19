import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Predictor de Rendimiento Estudiantil", layout="wide")
st.title("  Panel del Docente - Predicción de Riesgo")
st.write("Consulte las predicciones de riesgo académico de sus estudiantes.")

group_id = st.text_input("Ingrese el ID del Grupo (ej. 301-A, 302-B, 401-A)", value="301-A")

if st.button("Generar Reporte de Riesgo"):
    with st.spinner('Obteniendo datos y ejecutando el modelo...'):
        try:
            response = requests.get(
                f"http://127.0.0.1:8000/api/reports/group/{group_id}", timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if not data:
                    st.warning("No se encontraron datos para este grupo.")
                else:
                    st.success(f"Reporte generado con éxito para el grupo {group_id}")
                    
                    df = pd.DataFrame(data)
                    
                    def color_risk(val):
                        color = 'green' if val == 'Low' else 'orange' if val == 'Medium' else 'red'
                        return f'color: {color}; font-weight: bold'
                    
                    styled_df = df.style.map(color_risk, subset=['risk_level']) if hasattr(df.style, 'map') else df.style.applymap(color_risk, subset=['risk_level'])
                    
                    st.dataframe(styled_df, use_container_width=True)
                    
                    high_risk_count = len(df[df['risk_level'] == 'High'])
                    if high_risk_count > 0:
                        st.error(f"  {high_risk_count} estudiante(s) en Alto Riesgo. Se han enviado notificaciones automáticas a sus tutores académicos.")
                    else:
                        st.info("No hay estudiantes en Alto Riesgo.")
                        
            elif response.status_code == 404:
                st.error("Grupo no encontrado o sin estudiantes registrados.")
            elif response.status_code == 503:
                st.error("El servicio de datos no está disponible. Verifique que MongoDB esté en ejecución.")
            else:
                st.error(f"Error del servidor: {response.text}")
        except Exception as e:
            st.error(f"No se pudo conectar a la API backend: {e}. ¿Está en ejecución el servidor FastAPI?")