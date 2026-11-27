import os

import joblib

import predict


def test_model_file_loads():
    assert os.path.exists(predict.MODEL_PATH)
    assert joblib.load(predict.MODEL_PATH) is not None


def test_predict_returns_plausible_values():
    result = predict.predict(total_intensity_veh_per_hr=4000, hour_of_day=8)
    assert isinstance(result["no2_ug_m3_predicted"], float)
    assert 0 <= result["no2_ug_m3_predicted"] <= 200
    assert 0 <= result["no2_exceedance_risk"] <= 1


def test_risk_is_half_at_threshold():
    assert abs(predict.exceedance_risk(predict.THRESHOLD) - 0.5) < 1e-9