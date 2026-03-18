# Guarda este archivo como app.py
from flask import Flask, request, send_file
from flask_cors import CORS
import os
import io
import sys
import pandas as pd
import numpy as np
import camelot

# 1. Configuración de Ghostscript
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
    os.environ['PATH'] += os.pathsep + base_path

# 2. INICIALIZAR EL SERVIDOR 
app = Flask(__name__)
CORS(app)  


@app.route('/procesar', methods=['POST'])
def procesar_archivos():
    try:
        # 1. Recibir archivos del HTML
        archivo_pdf = request.files['pdf_file']
        archivo_excel = request.files['excel_file']

        # Guardar temporalmente el PDF para que camelot pueda leerlo
        pdf_path = "temp_seguridad.pdf"
        archivo_pdf.save(pdf_path)

        # 2. Tu lógica original de Camelot y Pandas
        tables = camelot.read_pdf(pdf_path, flavor='stream')
        
        if len(tables) == 0:
            return "No se encontraron tablas en el PDF", 400

        df = tables[1].df
        mask = df.apply(lambda row: row.astype(str).str.contains('Nit', case=False)).any(axis=1)
        
        if not mask.any():
            return "No se encontró la palabra 'Nit' en el PDF", 400

        indice_nit = mask.idxmax()
        tabla = df.iloc[indice_nit:].reset_index(drop=True)
        tabla.columns = tabla.iloc[0]
        planilla = tabla.iloc[1:].reset_index(drop=True)

        planilla['Nit'] = planilla['Nit'].str.replace('N', '', regex=False)
        planilla['Total'] = planilla['Total'].str.replace('$', '', regex=False).str.replace('.', '', regex=False)
        planilla['Nit'] = pd.to_numeric(planilla['Nit'], errors='coerce')
        planilla['Total'] = pd.to_numeric(planilla['Total'], errors='coerce')

        columnas_a_borrar = ['Código', 'Afiliados', 'Valor sin Mora', 'Valor Mora', '']
        existentes = [c for c in columnas_a_borrar if c in planilla.columns]
        planilla = planilla.drop(columns=existentes)
        planilla = planilla.groupby(['Nit'])['Total'].sum().reset_index()

        # 3. Lógica del Excel (Libro Mayor)
        lm = pd.read_excel(archivo_excel)
        lm['Nit / Cédula'] = lm['Nit / Cédula'].replace(860013816, 900336004, regex=False)
        lm['Nombre del Tercero'] = lm['Nombre del Tercero'].replace('INSTITUTO DE SEGUROS SOCIALES' , 'COLPENSIONES', regex=False)
        lm['Nit / Cédula'] = lm['Nit / Cédula'].replace(800256161, 890903790, regex=False)
        lm['Nombre del Tercero'] = lm['Nombre del Tercero'].replace('SEGUROS DE RIESGOS PROFESIONAL', 'ARL SURA', regex=False)
        lm['Subcuenta']=lm['Codigo de la cuenta'].astype(str).str[:6]
        
        condiciones = [
            lm['Subcuenta'] == '237005', lm['Subcuenta'] == '237010',
            lm['Subcuenta'] == '237020', lm['Subcuenta'] == '237015',
            lm['Subcuenta'] == '237025'
        ]
        resultados = ['23700501', '23701001', '23700501', '23701501', '23702501']
        
        lm['Subcuenta'] = np.select(condiciones, resultados, default=lm['Subcuenta'])
        lm['Nuevo Saldo'] = pd.to_numeric(lm['Nuevo Saldo'], errors='coerce')
        lm['Nit / Cédula'] = pd.to_numeric(lm['Nit / Cédula'], errors='coerce')
        lm = lm.groupby(['Nit / Cédula', 'Nombre del Tercero', 'Subcuenta'])['Nuevo Saldo'].sum().reset_index()
        lm = lm[lm['Nuevo Saldo'] != 0.0]

        # 4. Conciliación
        conciliacion = pd.merge(lm, planilla, left_on='Nit / Cédula', right_on='Nit', how='outer' )
        conciliacion['Diferencias'] = conciliacion['Nuevo Saldo'] + conciliacion['Total']
        conciliacion = conciliacion.rename(columns={'Nuevo Saldo':'CONTABILIDAD', 'Total':'NÓMINA/ ENLACE OPERATIVO', 'Nit / Cédula': 'Nit', 'Nombre del Tercero':'FONDOS', 'Subcuenta':'Cuenta'})
        conciliacion.sort_values(by='Cuenta', ascending=True, inplace=True)

        # 5. Guardar en memoria y enviar al HTML
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            conciliacion.to_excel(writer, sheet_name='Conciliación', index=False)
        
        output.seek(0)
        
        # Limpiar archivo temporal
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

        return send_file(output, download_name="Conciliacion_Pagos_Seguridad_Social.xlsx", as_attachment=True)

    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)