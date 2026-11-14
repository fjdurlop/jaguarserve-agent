"""Generate the synthetic demo catalog in data/demo_catalog/.

Every brand, model, price and stock number here is fictional. Re-run after editing the table:
    uv run python scripts/make_demo_catalog.py
"""

import csv
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "demo_catalog"
PRICE_VALID = "2027-06-30"
STOCK_AS_OF = "2026-11-10"

# sku, name, category, maker, summary_en, summary_es, specs(en), price, price_vis, stock, location, visibility
P = [
    (
        "VM-US-210",
        "SonoLite 210",
        "ultrasound",
        "Veltrion Medical",
        "Portable color Doppler ultrasound for point-of-care exams.",
        "Ultrasonido portátil con Doppler color para exámenes en el punto de atención.",
        {
            "Display": "15.6 in LCD",
            "Weight": "4.2 kg",
            "Battery": "2.5 h",
            "Probes": "convex, linear, phased",
            "Modes": "B, M, color Doppler, PW",
            "Storage": "256 GB",
        },
        18900,
        "public",
        4,
        "North warehouse",
        "public",
    ),
    (
        "VM-US-350",
        "SonoLite 350",
        "ultrasound",
        "Veltrion Medical",
        "Cart-based ultrasound with 4 probe ports for general imaging.",
        "Ultrasonido en carro con 4 puertos de sonda para imagen general.",
        {
            "Display": "21.5 in LCD + 13 in touch",
            "Probe ports": "4",
            "Modes": "B, M, color, PW, CW, elastography",
            "Weight": "62 kg",
            "Storage": "1 TB",
        },
        42500,
        "internal",
        1,
        "Central warehouse",
        "public",
    ),
    (
        "VM-US-HH1",
        "SonoPocket H1",
        "ultrasound",
        "Veltrion Medical",
        "Handheld wireless ultrasound probe that pairs with a tablet.",
        "Sonda de ultrasonido inalámbrica de mano que se conecta a una tableta.",
        {
            "Weight": "310 g",
            "Battery": "50 min scanning",
            "Connectivity": "Wi-Fi",
            "Depth": "up to 24 cm",
            "Modes": "B, M, color",
        },
        4950,
        "public",
        12,
        "North warehouse",
        "public",
    ),
    (
        "KI-PM-500",
        "VitaWatch 500",
        "patient monitor",
        "Kestrava Instruments",
        "Bedside patient monitor with ECG, SpO2, NIBP and temperature.",
        "Monitor de paciente de cabecera con ECG, SpO2, PNI y temperatura.",
        {
            "Display": "12.1 in touch",
            "Parameters": "ECG, SpO2, NIBP, TEMP, RESP",
            "Battery": "4 h",
            "Weight": "3.8 kg",
            "Alarm levels": "3",
        },
        3150,
        "public",
        20,
        "North warehouse",
        "public",
    ),
    (
        "KI-PM-800",
        "VitaWatch 800",
        "patient monitor",
        "Kestrava Instruments",
        "Modular ICU monitor with invasive pressure and EtCO2 modules.",
        "Monitor modular para UCI con módulos de presión invasiva y EtCO2.",
        {
            "Display": "17 in touch",
            "Parameters": "ECG 12-lead, SpO2, NIBP, IBP x4, EtCO2, TEMP x2",
            "Module slots": "6",
            "Battery": "2 h",
            "Network": "central station ready",
        },
        9800,
        "internal",
        6,
        "Central warehouse",
        "public",
    ),
    (
        "KI-PO-10",
        "OxiClip 10",
        "pulse oximeter",
        "Kestrava Instruments",
        "Fingertip pulse oximeter for spot checks.",
        "Oxímetro de pulso de dedo para mediciones puntuales.",
        {"SpO2 range": "70-100 %", "Accuracy": "+/- 2 %", "Battery": "2 x AAA, 30 h", "Weight": "50 g"},
        45,
        "public",
        300,
        "North warehouse",
        "public",
    ),
    (
        "KI-PO-60",
        "OxiDesk 60",
        "pulse oximeter",
        "Kestrava Instruments",
        "Tabletop pulse oximeter with trend memory and printer.",
        "Oxímetro de pulso de mesa con memoria de tendencias e impresora.",
        {"SpO2 range": "0-100 %", "Trend memory": "72 h", "Printer": "built-in thermal", "Battery": "6 h"},
        690,
        "public",
        25,
        "Central warehouse",
        "public",
    ),
    (
        "NH-IP-20",
        "FlowSure 20",
        "infusion pump",
        "Norhaven Devices",
        "Volumetric infusion pump with drug library support.",
        "Bomba de infusión volumétrica con soporte para biblioteca de fármacos.",
        {
            "Flow rate": "0.1-1200 mL/h",
            "Accuracy": "+/- 5 %",
            "Battery": "8 h at 25 mL/h",
            "Weight": "2.1 kg",
            "Occlusion alarm": "3 levels",
        },
        2400,
        "internal",
        30,
        "North warehouse",
        "public",
    ),
    (
        "NH-SP-10",
        "FlowSure S10",
        "syringe pump",
        "Norhaven Devices",
        "Syringe pump for 5 to 60 mL syringes.",
        "Bomba de jeringa para jeringas de 5 a 60 mL.",
        {
            "Syringe sizes": "5, 10, 20, 30, 50/60 mL",
            "Flow rate": "0.01-1500 mL/h",
            "Battery": "10 h",
            "Weight": "1.9 kg",
        },
        1750,
        "internal",
        18,
        "North warehouse",
        "public",
    ),
    (
        "NH-DF-3",
        "RescueLine AED 3",
        "defibrillator",
        "Norhaven Devices",
        "Automated external defibrillator with voice and CPR coaching.",
        "Desfibrilador externo automático con guía por voz y de RCP.",
        {
            "Energy": "150-200 J biphasic",
            "Shocks per battery": "200",
            "Standby battery life": "4 years",
            "Weight": "1.8 kg",
            "Ingress protection": "IP55",
        },
        1490,
        "public",
        15,
        "Central warehouse",
        "public",
    ),
    (
        "NH-DF-9",
        "RescueLine Pro 9",
        "defibrillator",
        "Norhaven Devices",
        "Manual and AED defibrillator-monitor with pacing.",
        "Desfibrilador-monitor manual y DEA con marcapasos.",
        {
            "Energy": "1-360 J biphasic",
            "Modes": "AED, manual, synchronized, pacing",
            "Display": "7 in color",
            "Battery": "5 h monitoring",
            "Weight": "6.5 kg",
        },
        11200,
        "internal",
        3,
        "Central warehouse",
        "public",
    ),
    (
        "QB-EC-12",
        "CardioTrace 12",
        "ECG",
        "Quillon Biomed",
        "12-lead electrocardiograph with interpretation and A4 printer.",
        "Electrocardiógrafo de 12 derivaciones con interpretación e impresora A4.",
        {
            "Leads": "12",
            "Printer": "A4 thermal",
            "Display": "10.1 in touch",
            "Memory": "1000 ECGs",
            "Battery": "3 h",
        },
        2890,
        "public",
        9,
        "North warehouse",
        "public",
    ),
    (
        "QB-EC-3",
        "CardioTrace 3",
        "ECG",
        "Quillon Biomed",
        "Compact 3-channel ECG for clinics.",
        "ECG compacto de 3 canales para consultorios.",
        {"Leads": "12 (3-channel print)", "Printer": "80 mm thermal", "Battery": "2 h", "Weight": "1.4 kg"},
        980,
        "public",
        14,
        "North warehouse",
        "public",
    ),
    (
        "QB-SP-1",
        "AirScore 1",
        "spirometer",
        "Quillon Biomed",
        "PC-based spirometer with disposable flow sensors.",
        "Espirómetro con PC y sensores de flujo desechables.",
        {
            "Flow range": "+/- 16 L/s",
            "Volume accuracy": "+/- 3 %",
            "Interface": "USB",
            "Sensor": "disposable",
        },
        1290,
        "public",
        7,
        "Central warehouse",
        "public",
    ),
    (
        "QB-VT-40",
        "BreathLine 40",
        "ventilator",
        "Quillon Biomed",
        "ICU ventilator with invasive and non-invasive modes.",
        "Ventilador para UCI con modos invasivos y no invasivos.",
        {
            "Modes": "VCV, PCV, SIMV, CPAP, BiPAP, NIV",
            "Tidal volume": "20-2000 mL",
            "Display": "15 in touch",
            "Battery": "2 h",
        },
        24800,
        "internal",
        2,
        "Central warehouse",
        "public",
    ),
    (
        "QB-VT-T2",
        "BreathLine T2",
        "ventilator",
        "Quillon Biomed",
        "Transport ventilator for ambulances and intra-hospital transfer.",
        "Ventilador de transporte para ambulancias y traslados intrahospitalarios.",
        {"Modes": "VCV, PCV, CPAP", "Tidal volume": "50-1500 mL", "Battery": "6 h", "Weight": "4.5 kg"},
        13900,
        "internal",
        0,
        "Central warehouse",
        "public",
    ),
    (
        "VM-XR-M1",
        "RayMove M1",
        "x-ray",
        "Veltrion Medical",
        "Mobile digital X-ray with wireless flat-panel detector.",
        "Rayos X digital móvil con detector plano inalámbrico.",
        {
            "Generator": "32 kW",
            "Detector": "35 x 43 cm wireless",
            "Battery": "full shift",
            "Weight": "380 kg",
        },
        78000,
        "internal",
        1,
        "Central warehouse",
        "public",
    ),
    (
        "VM-ST-23",
        "SteriCycle 23",
        "sterilizer",
        "Veltrion Medical",
        "Class B tabletop autoclave, 23 L chamber.",
        "Autoclave de mesa clase B, cámara de 23 L.",
        {
            "Chamber": "23 L",
            "Class": "B",
            "Cycle time": "35-60 min",
            "Water": "manual tank",
            "Power": "2.3 kW",
        },
        5200,
        "public",
        8,
        "North warehouse",
        "public",
    ),
    (
        "VM-ST-80",
        "SteriCycle 80",
        "sterilizer",
        "Veltrion Medical",
        "Floor-standing autoclave for central sterile services.",
        "Autoclave de piso para centrales de esterilización.",
        {"Chamber": "80 L", "Class": "B", "Doors": "single", "Power": "9 kW"},
        21500,
        "internal",
        2,
        "Central warehouse",
        "public",
    ),
    (
        "NH-BD-E5",
        "CareBed E5",
        "hospital bed",
        "Norhaven Devices",
        "Electric hospital bed with 5 functions and side rails.",
        "Cama hospitalaria eléctrica de 5 funciones con barandales.",
        {
            "Functions": "5 electric",
            "Safe working load": "250 kg",
            "Height range": "40-80 cm",
            "Battery backup": "yes",
        },
        3600,
        "public",
        11,
        "North warehouse",
        "public",
    ),
    (
        "NH-ST-2",
        "TransferGlide 2",
        "stretcher",
        "Norhaven Devices",
        "Hydraulic transport stretcher with radiolucent top.",
        "Camilla de transporte hidráulica con superficie radiotransparente.",
        {"Safe working load": "250 kg", "Height range": "55-90 cm", "Top": "radiolucent"},
        2950,
        "public",
        6,
        "North warehouse",
        "public",
    ),
    (
        "KI-SL-4",
        "LumaSurg 4",
        "surgical light",
        "Kestrava Instruments",
        "Dual-dome LED surgical light.",
        "Lámpara quirúrgica LED de doble cúpula.",
        {
            "Illuminance": "160,000 lux",
            "Color temperature": "4300 K",
            "Light field": "20 cm",
            "LED life": "50,000 h",
        },
        15800,
        "internal",
        2,
        "Central warehouse",
        "public",
    ),
    (
        "KI-SU-30",
        "VacuDrain 30",
        "suction unit",
        "Kestrava Instruments",
        "Portable surgical suction unit.",
        "Aspirador quirúrgico portátil.",
        {"Vacuum": "-90 kPa", "Flow": "30 L/min", "Jar": "1 L", "Battery": "45 min"},
        820,
        "public",
        16,
        "North warehouse",
        "public",
    ),
    (
        "QB-CF-12",
        "SpinLab 12",
        "centrifuge",
        "Quillon Biomed",
        "Benchtop centrifuge for clinical labs, 12 tubes.",
        "Centrífuga de mesa para laboratorio clínico, 12 tubos.",
        {"Max speed": "6000 rpm", "Capacity": "12 x 15 mL", "Timer": "1-99 min", "Noise": "< 60 dB"},
        1150,
        "public",
        10,
        "North warehouse",
        "public",
    ),
    (
        "QB-MS-2",
        "ClearView B2",
        "microscope",
        "Quillon Biomed",
        "Binocular lab microscope with LED illumination.",
        "Microscopio binocular de laboratorio con iluminación LED.",
        {"Objectives": "4x, 10x, 40x, 100x oil", "Illumination": "LED", "Stage": "mechanical"},
        640,
        "public",
        22,
        "North warehouse",
        "public",
    ),
    (
        "NH-EX-1",
        "ExamFlex 1",
        "examination table",
        "Norhaven Devices",
        "Electric examination table with adjustable backrest.",
        "Mesa de exploración eléctrica con respaldo ajustable.",
        {"Height range": "50-90 cm", "Safe working load": "200 kg", "Backrest": "0-75 degrees"},
        2100,
        "public",
        5,
        "Central warehouse",
        "public",
    ),
    (
        "KI-OC-5",
        "AeroPure 5",
        "oxygen concentrator",
        "Kestrava Instruments",
        "Stationary oxygen concentrator, 5 L/min.",
        "Concentrador de oxígeno estacionario, 5 L/min.",
        {"Flow": "0.5-5 L/min", "Purity": "93 % +/- 3 %", "Noise": "42 dB", "Power": "300 W"},
        890,
        "public",
        40,
        "North warehouse",
        "public",
    ),
    (
        "KI-NB-1",
        "MistAir 1",
        "nebulizer",
        "Kestrava Instruments",
        "Compressor nebulizer for home and clinic use.",
        "Nebulizador de compresor para uso en casa y consultorio.",
        {"Particle size": "MMAD 3 um", "Nebulization rate": "0.3 mL/min", "Noise": "55 dB"},
        85,
        "public",
        120,
        "North warehouse",
        "public",
    ),
    # internal-only products: not visible to public users at all
    (
        "VM-US-9X",
        "SonoLite 9X (preview)",
        "ultrasound",
        "Veltrion Medical",
        "Pre-release premium ultrasound; demo units for key accounts only.",
        "Ultrasonido premium previo al lanzamiento; unidades demo solo para cuentas clave.",
        {"Display": "23.8 in", "Probe ports": "5", "Modes": "all + shear-wave elastography"},
        96500,
        "internal",
        1,
        "Central warehouse",
        "internal",
    ),
    (
        "QB-VT-40R",
        "BreathLine 40 (refurbished)",
        "ventilator",
        "Quillon Biomed",
        "Refurbished ICU ventilator, 12-month warranty.",
        "Ventilador de UCI reacondicionado, garantía de 12 meses.",
        {"Modes": "VCV, PCV, SIMV, CPAP", "Warranty": "12 months"},
        14700,
        "internal",
        2,
        "Central warehouse",
        "internal",
    ),
]

ES_LABELS = {
    "Display": "Pantalla",
    "Weight": "Peso",
    "Battery": "Batería",
    "Probes": "Sondas",
    "Modes": "Modos",
    "Storage": "Almacenamiento",
    "Probe ports": "Puertos de sonda",
    "Connectivity": "Conectividad",
    "Depth": "Profundidad",
    "Parameters": "Parámetros",
    "Alarm levels": "Niveles de alarma",
    "Module slots": "Ranuras de módulo",
    "Network": "Red",
    "SpO2 range": "Rango SpO2",
    "Accuracy": "Exactitud",
    "Trend memory": "Memoria de tendencias",
    "Printer": "Impresora",
    "Flow rate": "Flujo",
    "Occlusion alarm": "Alarma de oclusión",
    "Syringe sizes": "Tamaños de jeringa",
    "Energy": "Energía",
    "Shocks per battery": "Descargas por batería",
    "Standby battery life": "Vida de batería en espera",
    "Ingress protection": "Protección de ingreso",
    "Leads": "Derivaciones",
    "Memory": "Memoria",
    "Flow range": "Rango de flujo",
    "Volume accuracy": "Exactitud de volumen",
    "Interface": "Interfaz",
    "Sensor": "Sensor",
    "Tidal volume": "Volumen corriente",
    "Generator": "Generador",
    "Detector": "Detector",
    "Chamber": "Cámara",
    "Class": "Clase",
    "Cycle time": "Tiempo de ciclo",
    "Water": "Agua",
    "Power": "Potencia",
    "Doors": "Puertas",
    "Functions": "Funciones",
    "Safe working load": "Carga de trabajo segura",
    "Height range": "Rango de altura",
    "Battery backup": "Batería de respaldo",
    "Top": "Superficie",
    "Illuminance": "Iluminancia",
    "Color temperature": "Temperatura de color",
    "Light field": "Campo de luz",
    "LED life": "Vida LED",
    "Vacuum": "Vacío",
    "Flow": "Flujo",
    "Jar": "Frasco",
    "Max speed": "Velocidad máxima",
    "Capacity": "Capacidad",
    "Timer": "Temporizador",
    "Noise": "Ruido",
    "Objectives": "Objetivos",
    "Illumination": "Iluminación",
    "Stage": "Platina",
    "Backrest": "Respaldo",
    "Purity": "Pureza",
    "Particle size": "Tamaño de partícula",
    "Nebulization rate": "Tasa de nebulización",
    "Warranty": "Garantía",
}


def sheet(sku, name, cat, maker, summary, specs, vis, lang):
    spec_head, use_head = ("Specifications", "Notes") if lang == "en" else ("Especificaciones", "Notas")
    label = (lambda k: k) if lang == "en" else (lambda k: ES_LABELS.get(k, k))
    note = (
        "Fictional device for demos. Ask sales for configurations and accessories."
        if lang == "en"
        else "Equipo ficticio para demostraciones. Consulte a ventas por configuraciones y accesorios."
    )
    rows = "\n".join(f"| {label(k)} | {v} |" for k, v in specs.items())
    cat = cat if lang == "en" else CAT_ES[cat]
    return (
        f"---\nsku: {sku}\ntitle: {maker} {name} ({cat})\nlang: {lang}\nvisibility: {vis}\n---\n"
        f"# {maker} {name}\n\n{summary}\n\n## {spec_head}\n\n| Spec | Value |\n|---|---|\n{rows}\n\n"
        f"## {use_head}\n\n{note}\n"
    )


CAT_ES = {
    "ultrasound": "ultrasonido",
    "patient monitor": "monitor de signos vitales",
    "pulse oximeter": "oxímetro de pulso",
    "infusion pump": "bomba de infusión",
    "syringe pump": "bomba de jeringa",
    "defibrillator": "desfibrilador",
    "ECG": "electrocardiógrafo",
    "spirometer": "espirómetro",
    "ventilator": "ventilador",
    "x-ray": "rayos X",
    "sterilizer": "esterilizador autoclave",
    "hospital bed": "cama hospitalaria",
    "stretcher": "camilla",
    "surgical light": "lámpara quirúrgica",
    "suction unit": "aspirador",
    "centrifuge": "centrífuga",
    "microscope": "microscopio",
    "examination table": "mesa de exploración",
    "oxygen concentrator": "concentrador de oxígeno",
    "nebulizer": "nebulizador",
}


SERVICE_EN = """---
title: Warranty and service (demo)
lang: en
visibility: public
---
# Warranty and service

All new devices in the demo catalog include a 24-month warranty unless the spec sheet says otherwise.
Refurbished devices include a 12-month warranty.

## Service visits

Preventive maintenance visits can be booked as a "service_visit" appointment. A technician confirms the
device model and serial number before the visit.

## Demos

Product demonstrations can be booked as a "demo" appointment, on site or online.
"""

SERVICE_ES = """---
title: Garantía y servicio (demo)
lang: es
visibility: public
---
# Garantía y servicio

Todos los equipos nuevos del catálogo demo incluyen 24 meses de garantía, salvo que la ficha técnica
indique otra cosa. Los equipos reacondicionados incluyen 12 meses de garantía.

## Visitas de servicio

Las visitas de mantenimiento preventivo se agendan como cita "service_visit". Un técnico confirma el modelo
y número de serie antes de la visita.

## Demostraciones

Las demostraciones de producto se agendan como cita "demo", en sitio o en línea.
"""

SALES_NOTES = """---
title: Sales notes Q4 (internal, fictional)
lang: en
visibility: internal
---
# Sales notes Q4 (internal)

Volume rule for distributors: 8 % off list price for 5 or more units of the same SKU.
The SonoLite 9X preview units are reserved for key accounts; do not quote to the public.
"""


def main() -> None:
    (OUT / "docs" / "en").mkdir(parents=True, exist_ok=True)
    (OUT / "docs" / "es").mkdir(parents=True, exist_ok=True)
    with (OUT / "products.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "sku",
                "name",
                "category",
                "manufacturer",
                "summary",
                "price",
                "currency",
                "price_valid_until",
                "price_visibility",
                "stock",
                "stock_location",
                "stock_as_of",
                "visibility",
            ]
        )
        for sku, name, cat, maker, s_en, s_es, specs, price, pvis, stock, loc, vis in P:
            w.writerow(
                [
                    sku,
                    name,
                    cat,
                    maker,
                    s_en,
                    f"{price:.2f}",
                    "USD",
                    PRICE_VALID,
                    pvis,
                    stock,
                    loc,
                    STOCK_AS_OF,
                    vis,
                ]
            )
            (OUT / "docs" / "en" / f"{sku}.md").write_text(
                sheet(sku, name, cat, maker, s_en, specs, vis, "en")
            )
            (OUT / "docs" / "es" / f"{sku}.md").write_text(
                sheet(sku, name, cat, maker, s_es, specs, vis, "es")
            )
    (OUT / "docs" / "en" / "warranty_service.md").write_text(SERVICE_EN)
    (OUT / "docs" / "es" / "garantia_servicio.md").write_text(SERVICE_ES)
    (OUT / "docs" / "sales_notes_internal.md").write_text(SALES_NOTES)
    print(f"wrote {len(P)} products to {OUT}")


if __name__ == "__main__":
    main()
