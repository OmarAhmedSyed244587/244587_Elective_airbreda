"""
train_model.py - fit a linear regression that predicts NO2 from traffic.

With so few rows a held-out test set is meaningless, so besides the in-sample
numbers we report leave-one-out (LOO) predictions: each row is predicted by a
model that never saw it. A baseline that always predicts the mean NO2 shows
whether the model learns anything at all.
"""

import joblib
import matplotlib

matplotlib.use("Agg")  # draw to a file, no window
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict

FEATURES = ["total_intensity_veh_per_hr", "hour_of_day"]

df = pd.read_csv("training_data.csv")
X, y = df[FEATURES], df["no2_ug_m3"]
print(f"Rows: {len(df)}")

model = LinearRegression().fit(X, y)
pred = model.predict(X)
print(f"\nIn-sample (the model has seen these rows):")
print(f"  R2  = {r2_score(y, pred):.3f}")
print(f"  MAE = {mean_absolute_error(y, pred):.2f} ug/m3")

loo = cross_val_predict(LinearRegression(), X, y, cv=LeaveOneOut())
print(f"\nLeave-one-out (each row predicted without seeing it):")
print(f"  R2  = {r2_score(y, loo):.3f}")
print(f"  MAE = {mean_absolute_error(y, loo):.2f} ug/m3")

baseline_mae = (y - y.mean()).abs().mean()
print(f"\nBaseline (always predict the mean {y.mean():.1f}): MAE = {baseline_mae:.2f} ug/m3")

print("\nCoefficients (change in NO2 per unit of each feature):")
for name, coef in zip(FEATURES, model.coef_):
    print(f"  {name}: {coef:+.5f}")
print(f"  intercept: {model.intercept_:.2f}")

joblib.dump(model, "model.pkl")
print("\nSaved model.pkl")

plt.figure(figsize=(7, 5))
plt.scatter(df["total_intensity_veh_per_hr"], y, c=df["hour_of_day"], cmap="viridis")
plt.colorbar(label="hour of day (Amsterdam)")
plt.xlabel("total traffic intensity (vehicles per hour, 4 sites)")
plt.ylabel("NO2 (ug/m3)")
plt.title("NO2 vs traffic, A27 Breda")
plt.tight_layout()
plt.savefig("no2_vs_traffic.png", dpi=120)
print("Saved no2_vs_traffic.png")