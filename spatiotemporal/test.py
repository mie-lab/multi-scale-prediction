import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from darts import TimeSeries, concatenate
from darts.datasets import AustralianTourismDataset
import pandas as pd
from darts.models import LinearRegressionModel, XGBModel
from darts.metrics import mae
from darts.dataprocessing.transformers import MinTReconciliator

from hierarchy_utils import aggregate_bookings, add_demand_groups
from station_hierarchy import StationHierarchy
from utils import get_error_group_level
from visualization import plot_error_evolvement
from optimal_transport import OptimalTransportLoss

in_path_data = "../data/bikes_montreal/test_data.csv"
in_path_stations = "../data/bikes_montreal/test_stations.csv"
out_path = "outputs"
os.makedirs(out_path, exist_ok=True)

demand_df = pd.read_csv(in_path_data)
stations_locations = pd.read_csv(in_path_stations).set_index("station_id")
demand_df["start_time"] = pd.to_datetime(demand_df["start_time"])

# make even smaller excerpt
max_station = 50
demand_df = demand_df[demand_df["station_id"] < max_station]
stations_locations = stations_locations[stations_locations.index < max_station]

# run the preprocessing
station_hierarchy = StationHierarchy(stations_locations)
demand_agg = aggregate_bookings(demand_df)
demand_agg = add_demand_groups(demand_agg, station_hierarchy.hier)

# train model
tourism_series = TimeSeries.from_dataframe(demand_agg)
tourism_series = tourism_series.with_hierarchy(
    station_hierarchy.get_darts_hier()
)
train, val = tourism_series[:-8], tourism_series[-8:]

# Model comparison
comparison = pd.DataFrame()
best_mean_error = np.inf
for ModelClass, model_name, params in zip(
    [LinearRegressionModel],  # XGBModel
    ["linear_multi"],  # , "linear_reconcile"
    [{"lags": 5}],  # , {"lags": 5}
):
    if "multi" in model_name:
        model = ModelClass(**params)
        model.fit(train)
        pred_raw = model.predict(n=len(val))
    else:  # independent forecast
        preds_collect = []
        for component in tourism_series.components:
            model = ModelClass(**params)
            model.fit(train[component])
            preds_collect.append(model.predict(n=len(val)))
        pred_raw = concatenate(preds_collect, axis="component")

    if "reconcile" in model_name:
        reconciliator = MinTReconciliator(method="wls_val")
        reconciliator.fit(train)
        pred = reconciliator.transform(pred_raw)
    else:
        pred = pred_raw

    station_hierarchy.add_pred(pred[0], f"pred_{model_name}_0")

    # check errors
    error_evolvement = get_error_group_level(
        pred, val, station_hierarchy.station_groups
    )
    # add to comparison
    comparison[model_name] = error_evolvement[:, 1]
    plot_error_evolvement(
        error_evolvement, os.path.join(out_path, f"errors_{model_name}.png")
    )
    current_mean_error = np.mean(error_evolvement[:, 1])
    if current_mean_error < best_mean_error:
        best_mean_error = current_mean_error
        best_model = model_name

comparison.index = error_evolvement[:, 0]

comparison.to_csv(os.path.join(out_path, "model_comparison.csv"))
plt.figure(figsize=(6, 6))
comparison.plot()
plt.savefig(os.path.join(out_path, "comparison.png"))

# Do optimal transport stuff with best pred
gt_col, pred_col = ("gt_0", f"pred_{best_model}_0")
station_hierarchy.add_pred(val[0], gt_col)

transport_loss = OptimalTransportLoss(station_hierarchy)
transport_loss.transport_from_centers(gt_col, pred_col)
transport_loss.transport_equal_dist(gt_col, pred_col)
