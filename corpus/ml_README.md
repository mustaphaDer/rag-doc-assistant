# Trustworthy ML: calibration, abstention, robustness and explanation stability

Can we **trust the probability** a medical classifier outputs? This project
measures four aspects of trustworthiness on the Wisconsin breast-cancer dataset
(569 tumours, 30 features, bundled with scikit-learn, so nothing to download):

| Question | Method |
|---|---|
| Q1 Are the probabilities honest? | ECE (own implementation), Brier score, NLL, reliability diagrams; post-hoc **temperature scaling, Platt scaling, isotonic regression** (own implementations) |
| Q2 Can the model know when to ask a doctor? | selective prediction: error at 80/90/100 % coverage, AURC |
| Q3 Does it hold under noisy measurements? | Gaussian noise of 0.25 / 0.5 / 1 × feature std added to the test set |
| Q4 Are explanations reliable? | permutation importance over 30 splits; top-5 stability (Jaccard) and agreement between two models |

**Protocol.** 30 stratified random splits: 60 % train / 20 % calibration / 20 % test.
Calibrators see only the calibration split. All numbers are **mean ± std over
the 30 splits**. Four models: logistic regression, Gaussian naive Bayes,
random forest, gradient boosting.

## Results

### Q1 Calibration (test set, 30 splits)

| Model | Calibration | Accuracy | ECE ↓ | NLL ↓ |
|---|---|---|---|---|
| Logistic regression | none | 0.980 ± 0.011 | 0.032 ± 0.007 | **0.066** ± 0.028 |
| | isotonic | 0.976 ± 0.013 | 0.025 ± 0.013 | 0.225 ± 0.236 |
| Gaussian naive Bayes | none | 0.934 ± 0.021 | 0.065 ± 0.020 | 0.630 ± 0.240 |
| | temperature | 0.934 ± 0.021 | 0.051 ± 0.015 | **0.180** ± 0.043 |
| | Platt | 0.935 ± 0.025 | 0.049 ± 0.017 | 0.193 ± 0.064 |
| | isotonic | 0.932 ± 0.022 | 0.045 ± 0.018 | 0.457 ± 0.299 |
| Random forest | none | 0.956 ± 0.020 | 0.048 ± 0.009 | 0.146 ± 0.085 |
| | Platt | 0.956 ± 0.020 | 0.046 ± 0.012 | 0.143 ± 0.065 |
| Gradient boosting | none | 0.964 ± 0.017 | 0.035 ± 0.013 | 0.128 ± 0.056 |
| | temperature | 0.964 ± 0.017 | 0.041 ± 0.012 | **0.106** ± 0.035 |

All 16 combinations, plus AUC and Brier score, are in `results/summary.json`.

![Reliability diagrams](results/reliability.png)

Findings:
1. **Naive Bayes is badly over-confident.** Temperature scaling, with a single
   parameter, cuts its NLL by 71 % (0.630 → 0.180).
2. **Logistic regression is already well calibrated.** No calibrator improved
   its NLL. Calibrating a model that doesn't need it costs data and adds variance.
3. **Isotonic regression has the lowest ECE in 3 of 4 models, yet the worst NLL
   of the three calibrators in all 4** (logistic regression: 0.225 ± 0.236 vs
   0.066 uncalibrated). I checked the cause for logistic regression: with about 114 calibration cases,
   its step function maps **82 %** of test cases to exactly 0 or 1. In 14 of the
   30 splits at least one of those certain predictions is wrong, and NLL
   punishes that hard. **A low ECE alone is not enough evidence.**
4. **A surprise I investigated:** temperature scaling should never change AUC,
   yet naive Bayes AUC fell from 0.987 to 0.976. The cause: **87.1 %** of its
   test probabilities lie within 10⁻⁶ of 0 or 1. Clipping them before the logit
   turns them into ties, and ties lower AUC. Saturated outputs hide ranking
   information that cannot be recovered afterwards.

### Q2 Selective prediction (Platt-calibrated, 30 splits)

| Model | Error, all cases | Error, 90 % most confident | Error, 80 % most confident |
|---|---|---|---|
| Logistic regression | 2.3 % ± 1.3 | 0.6 % ± 0.9 | **0.1 %** ± 0.4 |
| Gaussian naive Bayes | 6.5 % ± 2.5 | 2.6 % ± 1.2 | 2.1 % ± 1.2 |
| Random forest | 4.4 % ± 2.0 | 1.6 % ± 1.4 | 0.7 % ± 0.7 |
| Gradient boosting | 4.1 % ± 2.0 | 1.4 % ± 1.0 | 0.8 % ± 0.8 |

![Risk-coverage curves](results/risk_coverage.png)

If the 20 % least confident cases go to a human expert, the logistic-regression
error drops from 2.3 % to 0.1 %. Naive Bayes gains much less, because its
saturated confidences carry little ranking information (see finding 4).

### Q3 Robustness to measurement noise

| Model | Accuracy, clean → noise 1.0 | ECE, clean → noise 1.0 |
|---|---|---|
| Logistic regression | 0.980 → 0.912 | 0.032 → 0.070 |
| Gaussian naive Bayes | 0.934 → **0.602** | 0.065 → **0.392** |
| Random forest | 0.956 → 0.887 | 0.048 → 0.163 |
| Gradient boosting | 0.964 → 0.846 | 0.035 → 0.115 |

![ECE under noise](results/shift_ece.png)

**Calibration does not transfer to shifted data.** Platt scaling fitted on
clean data leaves naive Bayes at ECE 0.356 under noise 1.0. The probabilities
were "honest" only for the data the calibrator saw. This matters for medical
imaging, where scanners and hospitals change the input distribution.

### Q4 Explanation stability (permutation importance, 30 splits)

| | Logistic regression | Random forest |
|---|---|---|
| Mean Jaccard overlap of top-5 features between splits | **0.28** | 0.61 |
| Feature most often in top 5 | worst texture (27/30) | worst perimeter (26/30) |

The two models reach similar accuracy, yet their averaged top-5 features share
**only one feature** (worst radius). The dataset has strongly correlated
features (radius, perimeter and area measure almost the same thing), so
permutation importance spreads credit between them almost arbitrarily. **An
explanation from one model and one split should not be read as "what matters
medically."**

## Run it

```bash
pip install -r requirements.txt
python run_experiments.py --seeds 30   # about 6 minutes on a 4-core laptop; writes results/
python -m pytest -q                    # 7 tests: ECE by hand, symmetry, calibrators recover a known temperature
```

## Limits

- Small tabular dataset (569 cases). The questions transfer to images, but the
  numbers do not.
- Synthetic Gaussian noise is a simple stand-in for a real distribution shift
  (a new scanner, another hospital).
- ECE with 10 equal-width bins on about 114 test cases is noisy, which is why
  every number has a standard deviation and NLL/Brier are reported alongside it.
- Permutation importance with correlated features is a known weakness. Grouped
  importance or SHAP with a dependence-aware explainer would be next steps.

## Why I built it

To prepare for research on trustworthy AI (calibration, uncertainty,
explainability), as in the Fraunhofer ISST thesis on calibrated and explainable
X-ray AI and the trustworthy-ML work at RC Trust and the Lamarr Institute.
