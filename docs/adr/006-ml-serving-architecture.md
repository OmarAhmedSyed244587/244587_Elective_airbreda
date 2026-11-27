# ADR-006: ML Serving Architecture (Day 4)

- **Status:** Accepted
- **Date:** 2026-11-28

## Context

The API must return a predicted NO2 value and an `no2_exceedance_risk` between 0 and 1 for each
of the four NDW sites (hrl, hrr, vwd, vwa). The model has to be trained on data I collected myself
with the Day 1-3 ingestion pipeline.

What I actually have:

- **18 joined hourly rows**, starting 2026-11-26 (NO2 from the database joined to the four NDW
  sites on the hour; built by `build_training_data.py`, saved as `training_data.csv`).
- NO2 ranges 17.0-33.0 ug/m3 (mean 25.5). Total traffic (sum of the four sites) ranges 186-5,100
  vehicles/hour (mean 2,851).
- The data covers about one day, so one weather situation.
- A seventh constraint is the VM: 886 MB RAM (see ADR-005). The serving design has to be tiny.

## Decision

1. **Model: ordinary linear regression** (scikit-learn) on two features, `total_intensity_veh_per_hr`
   and `hour_of_day`, saved as `model.pkl`.
2. **Risk score:** a sigmoid centred on a threshold of **25 ug/m3** with steepness 0.2:
   `risk = 1 / (1 + exp(-0.2 * (predicted - 25)))`.
3. **Serving:** `predict.py` loads `model.pkl`, and `dashboard.py` imports it directly. There is
   no separate model server. The model is **baked into the dashboard's Docker image**, built with
   the exact library versions it was trained with (scikit-learn 1.9.1, numpy 2.5.5, pandas 3.1.1,
   joblib 1.6.0).
4. **Inputs at serving time:** the *total of all four sites*, and the Amsterdam local hour of the
   latest traffic reading, exactly as in training.
5. **If `predict()` fails**, `/site/{id}` still returns the real NO2 and traffic values, with
   `no2_ug_m3_predicted` and `no2_exceedance_risk` set to `null` and `"prediction_error": true`,
   and logs an ERROR event. It does not return a 500.

### Why linear regression is the right amount of model

With 18 rows and two features, a more flexible model (random forest, neural network) would fit
the noise in 18 points and look better on the training data while predicting worse. A linear model
has three numbers I can read and sanity-check:

- traffic: **+0.0009 ug/m3 per vehicle/hour** (about +0.9 per 1,000 vehicles/hour), the expected sign;
- hour of day: **-0.22 ug/m3 per hour**;
- intercept: 24.8.

What the numbers do and do not tell me:

| Measure | Value |
|---|---|
| R2, in-sample | 0.105 |
| R2, leave-one-out | -1.66 |
| MAE, in-sample | 3.45 ug/m3 |
| MAE, leave-one-out | 4.98 ug/m3 |
| MAE, predicting the mean (baseline) | 3.58 ug/m3 |

The model explains about 10% of the variation on the data it was fitted to, and under
leave-one-out it is **worse than just predicting the average**. So it has **no demonstrated
predictive skill yet**. I kept it because the assignment asks for a working end-to-end pipeline
first, and the pipeline, not the accuracy, is what this ADR designs. The hour-of-day coefficient
is confounded: with one day of data it mostly reflects that day's weather. A real example from the
live system: the actual reading was 35.0 ug/m3 while the model predicted 25.2.

**What would change the answer:** a few weeks to a full year of hourly rows (a year is about
8,760), plus weather features (wind speed and direction, temperature, rain) and weekday/holiday
flags. I would then evaluate with a time-based split (train on the past, test on the future) and
only move to a random forest or gradient boosting if it beats the linear model and the
predict-the-mean baseline on that test.

### How the risk score is derived

I convert the regression output with a sigmoid, rather than training a second classifier.

- **Threshold 25 ug/m3:** the WHO 2021 *24-hour* NO2 guideline. The EU and WHO annual values
  (EU 40, WHO 10) are annual averages, so they cannot be applied to a single hour. Comparing an
  hourly value with a 24-hour guideline is a mismatch, and I accept it as a simplification.
- **Steepness 0.2:** 5 ug/m3 above the threshold gives risk 0.73, and 10 above gives 0.88.
- **The score is not a calibrated probability.** It is a monotonic rescaling of the predicted
  value. Because the training mean (25.5) sits almost exactly at the threshold, and the model
  barely varies, the risk stays around 50% (I have seen 49-56%).
- The stretch goal (a logistic regression trained on a binary exceedance label) was **not built**.
  With 18 rows I would not trust it more than the sigmoid. It is the first thing to try once there
  is more data, because it would give a calibrated probability.

### Training-serving skew

Skew is when the model sees different inputs in production than it saw in training, so it gives
confident wrong answers without any error. In this design it could happen four ways, and each is
handled:

1. **Wrong aggregation:** the model was trained on the *sum of four sites*. Passing one site's
   flow (about 1,000 veh/h) would look like a quiet night, 3-4x too low. Every `/site/{id}`
   response therefore uses the four-site total.
2. **Wrong clock:** training used the Amsterdam local hour, so serving converts the timestamp to
   Europe/Amsterdam as well. Using UTC would shift the hour by one or two.
3. **Library drift:** a `model.pkl` loaded with a different scikit-learn can fail or behave
   differently. The image pins the same versions the model was trained with.
4. **Missing input:** if fewer than four sites have data, the total would be too low, so the
   prediction is skipped (`prediction_error: true`) instead of computed from a partial sum.

**Why baking the model into the image helps:** the model file, the code that uses it and the
library versions are built once and ship together as one immutable unit. Nothing on the live VM
retrains, downloads or silently swaps the model, so what I tested is what runs. Retraining live
would change predictions without review and would drag the training dependencies and database
load into a container that has about 50 MB of memory to itself.

### Why one station (NL10240) can serve all four NDW sites

The four sites (hrl, hrr, vwd, vwa) are measurement points on the same A27/Breda interchange, so
they share one local air mass and one air-quality reading represents all of them. The model
deliberately predicts one value for the whole interchange from the combined traffic. A design with
several separate corridors would be different: a single station would have to stand in for air
quality far away from where it is measured. **I would add a second station** when AirBreda monitors
a second interchange (or any corridor far enough away to have different traffic and different
exposure, for example a street canyon or a different wind situation), or when the model's errors
at one site are clearly different from the others.

### What `/site/{id}` returns when `predict()` fails

It returns the real, measured NO2 and traffic with the prediction fields set to `null` and
`"prediction_error": true`. The alternative was a failed request (HTTP 500). I chose to degrade
because measurements are the main product and the prediction is an add-on: a user who can still
see the actual NO2 and traffic is better served than one who sees an error. The flag makes the
failure visible and the ERROR log event makes it findable. If the **database** cannot be read,
there is nothing real to show, so that case returns 503.

## Consequences

- **Good:** a small, explainable model; serving costs almost no memory (the dashboard uses about
  54 MiB); the full path from raw data to prediction is reproducible (`build_training_data.py` ->
  `train_model.py` -> `model.pkl` -> `predict.py`) and covered by tests in `tests/test_model.py`.
- **Bad:** the model has no demonstrated skill, so the prediction and risk score are demo-quality
  and must not be used for decisions. The page and the ADR say so.
- **Retraining cost:** a new model means rebuilding the image and redeploying the dashboard
  (about 10 seconds of downtime, see ADR-005). The benefit is that every deployed model is
  versioned together with its code in Git.
- **Revisit when:** there are weeks of data (more rows, weather features), or exceedance risk is
  used for anything beyond a demonstration.