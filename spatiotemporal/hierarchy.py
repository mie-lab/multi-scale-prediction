import pandas as pd
import numpy as np
from sklearn.cluster import AgglomerativeClustering


def aggregate_bookings(demand_df, agg_by="day"):
    if agg_by == "day":
        demand_df[agg_by] = demand_df["start_time"].dt.date
    elif agg_by == "hour":
        demand_df[agg_by] = (
            demand_df["start_time"].dt.date.astype(str)
            + "-"
            + demand_df["start_time"].dt.hour.astype(str)
        )
    else:
        #     demand_df["second_hour"] = demand_df["hour"] // 2
        raise NotImplementedError()

    # count bookings per aggregatione time
    bookings_agg = demand_df.groupby([agg_by, "station_id"])[
        "duration_sec"
    ].count()
    bookings_agg = pd.DataFrame(bookings_agg).reset_index()
    bookings_agg.rename(
        {"duration_sec": "demand", agg_by: "timeslot"}, axis=1, inplace=True
    )
    bookings_agg = bookings_agg.pivot(
        index="timeslot", columns="station_id", values="demand"
    ).fillna(0)
    return bookings_agg


def clustering_algorithm(stations_locations):
    stations_locations.sort_values("station_id")
    clustering = AgglomerativeClustering(distance_threshold=0, n_clusters=None)
    clustering.fit(stations_locations[["start_x", "start_y"]])
    return clustering.children_


# # Deprecated
# def demand_hierarchy(bookings_agg, linkage, nr_samples=len(stations_locations)):
#     # initialize hierarchy
#     hierarchy = np.zeros((len(linkage) + nr_samples, nr_samples))
#     hierarchy[:nr_samples] = np.identity(nr_samples)

#     for i, pair in enumerate(linkage):
#         bookings_agg[i + nr_samples] = (
#             bookings_agg[pair[0]] + bookings_agg[pair[1]]
#         )
#         # add to hierarchy
#         row_for_child1 = hierarchy[pair[0]]
#         row_for_child2 = hierarchy[pair[1]]
#         hierarchy[i + nr_samples] = np.logical_or(
#             row_for_child1, row_for_child2
#         )

#     # convert to string columns
#     bookings_agg = (
#         bookings_agg.reset_index()
#         .rename_axis(None, axis=1)
#         .set_index("timeslot")
#     )
#     bookings_agg.columns = bookings_agg.columns.astype(str)

#     return bookings_agg, hierarchy


def hierarchy_to_dict(linkage, nr_samples):
    hier = {}
    for i, pair in enumerate(linkage):
        hier[str(i + nr_samples)] = list(pair.astype(str))
    return hier


def test_hierarchy(bookings_agg, hierarchy, test_node=800):
    # only works if only two
    #     if len(np.where(hierarchy[test_node])[0])==2:
    #         assert np.all(np.where(hierarchy[test_node]) == linkage[test_node - nr_samples])

    # assert that the column relations correspond to the hierarchy
    inds = np.where(hierarchy[test_node])[0]
    summed = bookings_agg[inds[0]].copy()
    for k in inds[1:]:
        summed += bookings_agg[k]
    assert all(bookings_agg[test_node] == summed)


def stations_to_hierarchy(stations_locations):
    assert stations_locations.index.name == "station_id"

    # cluster the stations
    clustering = AgglomerativeClustering(distance_threshold=0, n_clusters=None)
    clustering.fit(stations_locations[["start_x", "start_y"]])

    # convert into dictionary as a basis for the new station-group df
    station_groups = stations_locations.reset_index()
    station_groups["nr_stations"] = 1
    station_groups["group"] = (
        station_groups["station_id"].astype(int).astype(str)
    )
    station_groups_dict = (
        station_groups.drop(["station_id"], axis=1).swapaxes(1, 0).to_dict()
    )

    linkage = clustering.children_
    nr_samples = len(stations_locations)

    hier = {}

    for j, pair in enumerate(linkage):
        node1, node2 = (
            station_groups_dict[pair[0]],
            station_groups_dict[pair[1]],
        )

        # init new node
        new_node = {}
        # compute running average of the coordinates
        new_nr_stations = node1["nr_stations"] + node2["nr_stations"]
        new_node["nr_stations"] = new_nr_stations
        new_node["start_x"] = (
            node1["start_x"] * node1["nr_stations"]
            + node2["start_x"] * node2["nr_stations"]
        ) / new_nr_stations
        new_node["start_y"] = (
            node1["start_y"] * node1["nr_stations"]
            + node2["start_y"] * node2["nr_stations"]
        ) / new_nr_stations

        # add group name
        new_node["group"] = "Group_" + str(j)

        # add to overall dictionary
        station_groups_dict[j + nr_samples] = new_node

        # add to darts hierarchy
        #         darts_hier[node1["group"]] = new_node["group"]
        #         darts_hier[node2["group"]] = new_node["group"]
        hier[new_node["group"]] = [node1["group"], node2["group"]]

    station_groups = (
        pd.DataFrame(station_groups_dict).swapaxes(1, 0).set_index("group")
    )
    return station_groups, hier


def add_demand_groups(demand_agg, hier):
    # convert to string columns
    demand_agg = (
        demand_agg.reset_index().rename_axis(None, axis=1).set_index("timeslot")
    )
    demand_agg.columns = demand_agg.columns.astype(str)
    demand_agg.index = pd.to_datetime(demand_agg.index)

    for key, pair in hier.items():
        demand_agg[key] = demand_agg[pair[0]] + demand_agg[pair[1]]
    return demand_agg


def hier_to_darts(hierarchy: dict):
    darts_hier = {}
    for key, pair in hierarchy.items():
        for p in pair:
            darts_hier[p] = key
    return darts_hier
