import os
import torchmetrics
import torch
from darts.models import (
    LinearRegressionModel,
    XGBModel,
    NHiTSModel,
    Croston,
    LightGBMModel,
)
from darts.utils.timeseries_generation import (
    datetime_attribute_timeseries as dt_attr,
)
from darts.dataprocessing.transformers import Scaler


class CovariateWrapper:
    def __init__(
        self,
        time_series,
        train_cutoff,
        lags_past_covariates=0,
        dt_covariates=True,
    ) -> None:
        self.lags_past_covariates = lags_past_covariates
        self.train_cutoff = train_cutoff

        # if 0, don't return any covariates
        if self.lags_past_covariates == 0:
            return None

        if dt_covariates:
            self.covariates = self.design_dt_covariates(time_series)

    def get_train_covariates(self):
        if self.lags_past_covariates == 0:
            return None
        else:
            return self.covariates[: self.train_cutoff]

    def get_val_covariates(self, val_index, steps_ahead):
        if self.lags_past_covariates == 0:
            return None
        else:
            start_at = val_index - self.lags_past_covariates
            return self.covariates[start_at : val_index + steps_ahead]

    def design_dt_covariates(self, time_series):
        # make dt attributes and stack
        day = dt_attr(time_series, attribute="day")
        weekday = dt_attr(time_series, attribute="weekday")
        covariates = day.stack(weekday)
        month = dt_attr(time_series, attribute="month")
        covariates = covariates.stack(month)
        hour = dt_attr(time_series, attribute="hour")
        covariates = covariates.stack(hour)
        # scale
        scaler_dt = Scaler()
        scaled_covariates = scaler_dt.fit_transform(covariates)
        return scaled_covariates


class ModelWrapper:
    def __init__(
        self, model_class, covariate_wrapper, lags_past_covariates=0, **kwargs
    ) -> None:
        # store model args
        self.model_args = kwargs
        # set working directory
        self.work_dir = os.path.join(
            self.model_args["model_path"], self.model_args["model_name"]
        )
        os.makedirs(self.work_dir, exist_ok=True)

        # decide if using past covariates
        encoders = {}
        if lags_past_covariates == 0:
            self.model_args["lags_past_covariates"] = None
        else:
            self.model_args["lags_past_covariates"] = lags_past_covariates
            encoders["cyclic"] = {"past": ["hour", "day", "weekday"]}

        # set model class and model kwargs
        if model_class == "linear":
            ModelClass = LinearRegressionModel
            model_kwargs = {"lags": self.model_args["lags"]}
        elif model_class == "nhits":
            ModelClass = NHiTSModel
            model_kwargs = {
                "input_chunk_length": self.model_args["lags"],
                "n_epochs": self.model_args["n_epochs"],
                "num_stacks": self.model_args["num_stacks"],
                "work_dir": self.work_dir,
                "model_name": self.model_args["model_name"],
                "log_tensorboard": True,
                "torch_metrics": torchmetrics.MetricCollection(
                    torchmetrics.MeanSquaredError(), torch.nn.CrossEntropyLoss()
                ),
            }
            if kwargs["x_scale"]:
                encoders["transformer"] = Scaler()
                model_kwargs["add_encoders"] = encoders

        elif model_class == "lightgbm":
            ModelClass = LightGBMModel
            model_kwargs = {
                "lags": self.model_args["lags"],
            }
        elif model_class == "xgb":
            ModelClass = XGBModel
            model_kwargs = {"lags": self.model_args["lags"]}
        else:
            raise ValueError("Model name unknown")

        # add past covariates for all of them
        if model_class != "nhits":
            model_kwargs["lags_past_covariates"] = self.model_args[
                "lags_past_covariates"
            ]
        model_kwargs["output_chunk_length"] = self.model_args[
            "output_chunk_length"
        ]

        # add loss function
        if "loss_fn" in self.model_args:
            model_kwargs["loss_fn"] = self.model_args["loss_fn"]

        # initialize
        self.model = ModelClass(**model_kwargs)
        # load model if desired
        load_model = self.model_args["load_model_name"]
        if load_model is not None:
            print("Loading model from", load_model)
            self.model.load(
                os.path.join(
                    self.model_args["model_path"], load_model, "model.pt"
                )
            )

        self.covariate_wrapper = covariate_wrapper

    def fit(self, series):
        self.model.fit(
            series,
            past_covariates=self.covariate_wrapper.get_train_covariates(),
        )

    def predict(self, n, series, val_index):
        pred = self.model.predict(
            n=n,
            series=series,
            past_covariates=self.covariate_wrapper.get_val_covariates(
                val_index, n
            ),
        )
        return pred

    def save(self):
        self.model.save(os.path.join(self.work_dir, "model.pt"))
