import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Student Performance Predictor", layout="wide")

st.title("👨‍🏫 Teacher Dashboard - Risk Prediction")
st.write("View the academic risk predictions for your students.")

group_id = st.text_input("Enter Group ID (e.g. 301-A, 302-B, 401-A)", value="301-A")

if st.button("Generate Risk Report"):
    with st.spinner('Fetching data and running ML pipeline...'):
        try:
            # Assuming FastAPI is running on localhost:8000
            response = requests.get(f"http://127.0.0.1:8000/api/reports/group/{group_id}")
            
            if response.status_code == 200:
                data = response.json()
                if not data:
                    st.warning("No data found for this group.")
                else:
                    st.success(f"Report generated successfully for group {group_id}")
                    
                    df = pd.DataFrame(data)
                    
                    # Style function requires pandas >= 1.3.0
                    def color_risk(val):
                        color = 'green' if val == 'Low' else 'orange' if val == 'Medium' else 'red'
                        return f'color: {color}; font-weight: bold'
                    
                    # applymap is deprecated in newer pandas, map is used instead. But to be safe across versions, use map if available.
                    styled_df = df.style.map(color_risk, subset=['risk_level']) if hasattr(df.style, 'map') else df.style.applymap(color_risk, subset=['risk_level'])
                    
                    st.dataframe(styled_df, use_container_width=True)
                    
                    high_risk_count = len(df[df['risk_level'] == 'High'])
                    if high_risk_count > 0:
                        st.error(f"⚠️ {high_risk_count} student(s) at High Risk. Automated notifications have been sent to their Academic Tutors.")
                    else:
                        st.info("No students at High Risk.")
                    
            elif response.status_code == 404:
                st.error("Group not found or no students registered.")
            else:
                st.error(f"Error from server: {response.text}")
        except Exception as e:
            st.error(f"Failed to connect to backend API: {e}. Is the FastAPI server running?")
