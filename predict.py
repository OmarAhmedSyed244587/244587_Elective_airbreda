"""
predict.py - predict NO2 from traffic and turn it into an exceedance risk.

The model (model.pkl, a linear regression trained by train_model.py) is loaded
once. Risk is a sigmoid centred on THRESHOLD: 0.5 exactly at the threshold,
higher above it, lower below it.

THRESHOLD = 25 ug/m3 is the WHO 2021 24-hour guideline for NO2. It is a daily
guideline, but we apply it to hourly values, which is stricter than the
guideline itself. The EU hourly limit (200) would give risk ~0 for every
reading we have, so it would tell the dashboard nothing.
"""

import os

import joblib
import numpy as np
import pandas as pd

FEATURES = ["total_intensity_veh_per_hr", "hour_of_day"]
THRESHOLD = 25.0  # ug/m3
STEEPNESS = 0.2
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.pkl")

_model = None


def _load_model():
    global _model
    if _model is None:
        _model = joblib.load(MODEL_PATH)
    return _model


def exceedance_risk(predicted_no2, threshold=THRESHOLD, steepness=STEEPNESS):
    return float(1 / (1 + np.exp(-steepness * (predicted_no2 - threshold))))


def predict(total_intensity_veh_per_hr, hour_of_day):
    """Return {"no2_ug_m3_predicted": float, "no2_exceedance_risk": float in 0..1}."""
    row = pd.DataFrame([[total_intensity_veh_per_hr, hour_of_day]], columns=FEATURES)
    value = float(_load_model().predict(row)[0])
    return {
        "no2_ug_m3_predicted": round(value, 2),
        "no2_exceedance_risk": round(exceedance_risk(value), 3),
    }