from modules.general_utils import month_year
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.linear_model import HuberRegressor, Lasso
from sklearn.preprocessing import PolynomialFeatures
import numpy as np
import pandas as pd

# Rimuovi keras se non usi LSTM/Sequential (TensorFlow non supporta Python 3.13.x)
# from keras.models import Sequential
# from keras.layers import LSTM, Dense, Dropout


def find_best_model(X, y):
    # Definire il range dei parametri da testare
    param_grid = {
        "polynomialfeatures__degree": list(
            np.arange(0, 3, 1)
        ),  # Gradi polinomiali da testare
        "lasso__alpha": list(
            np.arange(0.001, 2.501, 0.05)
        ),  # Valori di alpha da testare
    }

    # Creare un pipeline con PolynomialFeatures e Lasso Regression
    pipeline = Pipeline(
        [
            ("polynomialfeatures", PolynomialFeatures()),
            ("lasso", Lasso(max_iter=1000000, tol=0.0001)),
        ]
    )

    # Utilizzare GridSearchCV per trovare il miglior modello e il grado polinomiale
    grid_search = GridSearchCV(
        pipeline,
        param_grid,
        cv=3,
        scoring="neg_mean_absolute_error",
        n_jobs=-1,
    )
    grid_search.fit(X, y)

    # Il miglior modello trovato dalla ricerca su griglia
    best_model_lasso = grid_search.best_estimator_
    best_score_lasso = -grid_search.best_score_
    best_params_lasso = grid_search.best_params_
    best_degree_lasso = best_params_lasso["polynomialfeatures__degree"]
    best_alpha_lasso = best_params_lasso["lasso__alpha"]

    print(
        f"Best polynomial degree: {best_degree_lasso}, Best alpha_lasso: {best_alpha_lasso}"
    )
    print(f"Best MAE score_lasso from GridSearchCV: {best_score_lasso}")

    pipeline = Pipeline([("regressor", HuberRegressor())])

    # Definire il range dei parametri da testare (potrebbe essere esteso a seconda delle esigenze)
    param_grid = {"regressor__alpha": list(np.arange(0.001, 2.501, 0.05))}

    # Utilizzare GridSearchCV per trovare il miglior modello
    grid_search = GridSearchCV(
        pipeline,
        param_grid,
        cv=3,
        scoring="neg_mean_absolute_error",
        n_jobs=-1,
    )
    grid_search.fit(X, y)

    # Il miglior modello trovato dalla ricerca su griglia
    best_model_huber = grid_search.best_estimator_
    best_score_huber = -grid_search.best_score_
    best_params_huber = grid_search.best_params_

    print(f"Best hyperparameters_huber :{best_params_huber}")
    print(f"Best MAE score_huber from GridSearchCV: {best_score_huber}")

    # Definire il range dei parametri da testare per Gradient Boosting
    param_grid_gb = {
        "n_estimators": [100, 200, 300],
        "learning_rate": [0.01, 0.1, 0.2],
        "max_depth": [3, 4, 5],
        "min_samples_split": [2, 3, 4],
    }

    gb_model = GradientBoostingRegressor()

    grid_search_gb = GridSearchCV(
        gb_model, param_grid_gb, cv=3, scoring="neg_mean_absolute_error", n_jobs=-1
    )
    grid_search_gb.fit(X, y)

    best_model_gb = grid_search_gb.best_estimator_
    best_score_gb = -grid_search_gb.best_score_
    best_params_gb = grid_search_gb.best_params_

    print(f"Best parameters for Gradient Boosting: {best_params_gb}")
    print(f"Best MAE score from GridSearchCV for Gradient Boosting: {best_score_gb}")

    # Confronto dei punteggi per determinare il modello migliore
    best_score, best_model = min(
        (best_score_lasso, best_model_lasso),
        (best_score_huber, best_model_huber),
        (best_score_gb, best_model_gb),
        key=lambda x: x[0],
    )

    print(
        f"Best Model decided: {type(best_model).__name__}, Best MAE score: {type(best_score).__name__}"
    )

    return best_model


def project_future_values(
    data_collected, data_for_projection, months_to_project, inflation_rate
):
    # Assicurati che month_year sia definita altrove
    # month, year = month_year()  # Removed unused variable assignment
    date_index = pd.date_range(start="2021-09", periods=len(data_collected), freq="MS")
    df_project = pd.DataFrame(
        data_for_projection, index=date_index, columns=["Data_for_Projection"]
    )

    # Prepare data for non-linear regression
    X = np.arange(len(df_project)).reshape(-1, 1)
    y = df_project["Data_for_Projection"].values

    best_model = find_best_model(X, y)
    best_model.fit(X, np.asarray(y))

    # Create the time index for future months
    future_index = pd.date_range(
        start=df_project.index[-1] + pd.offsets.MonthBegin(1),
        periods=months_to_project,
        freq="MS",
    )

    # Prepare data for prediction
    X_future = np.arange(len(df_project), len(df_project) + months_to_project).reshape(
        -1, 1
    )

    # Predict new values
    future_values = best_model.predict(X_future)

    # Calculate the monthly inflation from the annual rate
    monthly_inflation_rate = (1 + inflation_rate) ** (1 / 12) - 1

    # Adjust the predicted values for inflation
    inflation_adjustments = (1 + monthly_inflation_rate) ** np.arange(
        1, months_to_project + 1
    )
    adjusted_future_values = future_values * inflation_adjustments

    # Merge historical data with predictions
    future_df = pd.DataFrame(
        adjusted_future_values, index=future_index, columns=["ProjectedDataCollected"]
    )
    total_index = date_index.append(future_index)
    combined_data = np.concatenate([data_collected, adjusted_future_values])
    result_df = pd.DataFrame(
        combined_data, index=total_index, columns=["Data_Combined"]
    )

    return future_df, result_df, total_index
