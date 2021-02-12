# Copyright 2020 The Maritime Whale Authors. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE.txt file.
#
# Processes wind and vessel data. Performs simple analysis.

from match_wind_data import *
from datetime import *
from meetpass import *

import pandas as pd
import math
import sys

# TODO: need to generalize this to apply to any port desired; will need to
# do the same for main, run, plot, etc

# vessel (AIS) types that should be automatically purged from analysis
# see details at https://api.vesselfinder.com/docs/ref-aistypes.html
AUTO_BLACKLIST = [30, 31, 32, 33, 34, 35, 36, 37, 51, 52, 53, 55, 57, 58, 59]
SUB_PANAMAX = 656 # threshold in feet
M_TO_FT = 3.28 # meters to feet (conversion)

def _sanitize_vmr(df):
    """Filters entries with '511' error, impossibly high speed, abnormally
    high vessel width, as well as singletons (only one entry) from vessel
    movement DataFrame.

    Args:
        df: Vessel movement DataFrame.

    Returns:
        Sanitized vessel movement report DataFrame.
    """
    df = df[~df.index.isin(df[df["Beam ft"] >= 500].index)]
    df = df[~df.index.isin(df[df["Course"] == 511].index)]
    df = df[~df.index.isin(df[df["Heading"] == 511].index)]
    df = df[~df.index.isin(df[df["VSPD kn"] >= 40].index)]
    df = df[~df.MMSI.isin(
             df.MMSI.value_counts()[df.MMSI.value_counts() == 1].index.values)]
    return df

def _wrangle_vmr(df, rename):
    """Rounds, renames, and sanitizes vessel movment DataFrame. Creates new
    columns.

    Args:
        df: Vessel movement DataFrame.

    Returns:
        Cleaned vessel movement report DataFrame.
    """
    df.rename(rename, axis=1, inplace=True)
    df["LOA ft"] = (df["A"] + df["B"]) * M_TO_FT
    df["LOA ft"] = df["LOA ft"].round(0)
    df["Beam ft"] = (df["C"] + df["D"]) * M_TO_FT
    df["Beam ft"] = df["Beam ft"].round(0)
    df["Latitude"] = df["Latitude"].round(5)
    df["Longitude"] = df["Longitude"].round(5)
    df = _sanitize_vmr(df)
    df = df[df["LOA ft"] >= SUB_PANAMAX] # filter out sub-panamax class vessels
    df["Date/Time UTC"] = df["Date/Time UTC"].str.strip("UTC")
    df["Date/Time UTC"] = pd.to_datetime(df["Date/Time UTC"])
    # df = df[["Date/Time UTC", "Name", "MMSI", "LOA ft", "Latitude", "Longitude",
    #          "Course", "AIS Type", "Heading", "VSPD kn", "Beam ft"]]
    df = df.loc[:, (["Date/Time UTC", "Name", "MMSI", "LOA ft", "Latitude",
                     "Longitude", "Course", "AIS Type", "Heading", "VSPD kn",
                     "Beam ft"])]
    return df

def _wrangle_live(df):
    # TODO: Add into one function above that checks type
    """Rounds, renames, and sanitizes vessel movment DataFrame. Creates new
    columns.

    Args:
        df: Vessel movement DataFrame.

    Returns:
        Cleaned vessel movement report DataFrame.
    """
    # DATETIME (UTC) should be timestamp
    #AIS TYPE should be TYPE
    df.rename({"DATETIME (UTC)": "UTC", "NAME": "Name",
               "LATITUDE": "Latitude", "LONGITUDE": "Longitude",
               "SPEED": "VSPD kn", "COURSE": "Course", "HEADING":
               "Heading", "AIS TYPE": "AIS Type"}, axis=1, inplace=True)
    df["LOA ft"] = (df["A"] + df["B"]) * M_TO_FT
    df["LOA ft"] = df["LOA ft"].round(0)
    df["Beam ft"] = (df["C"] + df["D"]) * M_TO_FT
    df["Beam ft"] = df["Beam ft"].round(0)
    df["Latitude"] = df["Latitude"].round(5)
    df["Longitude"] = df["Longitude"].round(5)
    df = _sanitize_vmr(df)
    df = df[df["LOA ft"] >= SUB_PANAMAX] # filter out sub-panamax class vessels
    df["UTC"] = [df["UTC"].values[i][10:19] for i in range(len(df["UTC"].values))]
    # df = df[["UTC", "Name", "MMSI", "LOA ft", "Latitude", "Longitude",
    #          "Course", "AIS Type", "Heading", "VSPD kn", "Beam ft"]]
    df = df.loc[:, ("UTC", "Name", "MMSI", "LOA ft", "Latitude", "Longitude",
             "Course", "AIS Type", "Heading", "VSPD kn", "Beam ft")]
    return df

def _filter_blacklisters(df, blacklist):
    """Checks vessel AIS types and ommits blacklisted vessel types from the
    filtered data. Appends ommitted vessels' MMSI's to blacklist.txt.

    Args:
        df: Vessel movement DataFrame.

    Returns:
        Filtered vessel movement DataFrame.
    """
    df = df[~df.MMSI.isin(blacklist)]
    new_blacklisters = []
    for j in range(df.shape[0]):
        if df.iloc[j]["AIS Type"] in AUTO_BLACKLIST:
            new_blacklisters.append(df.iloc[j].MMSI)
    with open("../cache/blacklist.txt", "a") as f:
        contents = [str(mmsi) for mmsi in new_blacklisters]
        if contents:
            f.write("\n".join(contents) + "\n")
    df = df[~df.MMSI.isin(new_blacklisters)]
    return df

def _fold_vmr(ports, i):
    """Reduces movement report to a DataFrame with a single entry for each
    vessel at the point of it's maximum speed in the channel. Includes a column
    with the vessel's mean speed.
    """
    mean = pd.DataFrame(ports[i].groupby(["Name", "MMSI"])["VSPD kn"]
           .mean()).rename({"VSPD kn": "Mean Speed kn"}, axis=1).round(1)
    maxes = pd.DataFrame(ports[i].groupby(["Name", "MMSI"])["VSPD kn"]
            .max()).rename({"VSPD kn": "Max Speed kn"}, axis=1)
    merged_speeds = maxes.merge(mean, on=["Name", "MMSI"])
    max_dict = merged_speeds["Max Speed kn"].to_dict()
    columns = {"Longitude":[], "Latitude":[], "Date/Time UTC":[],
               "LOA ft":[], "Course":[], "AIS Type":[], "WSPD mph":[],
               "GST mph":[], "WDIR degT":[], "Buoy Source":[], "Beam ft":[],
               "Heading":[], "Course Behavior":[], "Effective Beam ft":[],
               "Class":[], "Location":[], "Yaw deg":[], "Transit":[],
               "% Channel Occupied":[]}
    # grab remaining data based on max speed position
    for key, value in max_dict.items():
        for k in columns.keys():
            columns[k].append(ports[i][(ports[i].Name == key[0]) &
                             (ports[i]["VSPD kn"] == value)][k].iloc[0])
    for key in columns.keys():
        merged_speeds[key] = columns[key]
    merged_speeds = merged_speeds.reset_index()
    fold_res = merged_speeds
    fold_res.sort_values("Max Speed kn", ascending=False, inplace=True)
    return fold_res

def _add_channel_occ(ports, i):
    """Creates the channel occupancy column."""
    # total channel width for CH and SV are 1000 and 600 ft respectively,
    # but vary based on Class and transit condition
    channel_width = [[800, 400, 1000, 500], [600, 300, 600, 300]]
    # create % channel occupancy column for each vessel position based on
    # effective beam, transit, and corresponding channel width
    for row in range(len(ports[i])):
        vessel_class = ports[i].loc[row, "Class"]
        transit_type = ports[i].loc[row, "Transit"]
        eff_beam = ports[i].loc[row, "Effective Beam ft"]
        if ((vessel_class == "Post-Panamax") &
            (transit_type == "One-way Transit")):
            occ = (eff_beam / channel_width[i][0]) * 100
            ports[i].loc[row, "% Channel Occupied"] = round(occ, 2)
        elif ((vessel_class == "Post-Panamax") &
              (transit_type == "Two-way Transit")):
            occ = (eff_beam / channel_width[i][1]) * 100
            ports[i].loc[row, "% Channel Occupied"] = round(occ, 2)
        elif ((vessel_class == "Panamax") &
              (transit_type == "One-way Transit")):
            occ = (eff_beam / channel_width[i][2]) * 100
            ports[i].loc[row, "% Channel Occupied"] = round(occ, 2)
        elif ((vessel_class == "Panamax") &
              (transit_type == "Two-way Transit")):
            occ = (eff_beam / channel_width[i][3]) * 100
            ports[i].loc[row, "% Channel Occupied"] = round(occ, 2)
        else:
            sys.stderr.write("Error: Undefined Class and " +
                             "transit combination...\n")
            ports[i].loc[row, "% Channel Occupied"] = float("NaN")
    return ports[i]

def _add_vessel_class(df):
    """Creates 'Class' column based on vessel LOA ft."""
    df.loc[:, "Class"] = "Panamax"
    post_pan = df.index.isin(df[df["LOA ft"] > 965].index)
    df.loc[post_pan, "Class"] = "Post-Panamax"
    return df

def _course_behavior(df, ranges):
    """Creates 'Course Behavior' column based on channel specific course ranges.
    """
    course_behavior = ("Outbound", "Inbound")
    # filter on course ranges to isolate inbound and outbound ships only
    df = df[(df.Course >= ranges[0][0]) & (df.Course <= ranges[0][1]) |
            (df.Course >= ranges[1][0]) & (df.Course <= ranges[1][1])]
    df.Course = round(df.Course).astype("int")
    df.loc[:, "Course Behavior"] = df.loc[:, "Course"]
    # replace course values with general inbound and outbound behavior
    courses = {}
    for behavior, bounds in zip(course_behavior, ranges):
        lower_bound = bounds[0]
        upper_bound = bounds[1]
        for j in range(lower_bound, upper_bound + 1):
            courses[j] = behavior
    # TODO: Review this with David
    # Not sure why this had astype("str") before..
    # df.loc[:, "Course Behavior"] = (df.loc[:, "Course Behavior"]
    #                                 .replace(courses).astype("str"))
    df.loc[:, "Course Behavior"].replace(courses, inplace=True)
    return df

def process_chunk(path):
    """Processes LiveData chunk. Creates other relevant columns."""
    # TODO: need to test (think of other edge cases this needs to handle)
    # TODO: decompose and document new functions
    blacklist = [int(mmsi) for mmsi in open("../cache/blacklist.txt",
                                            "r").readlines()]
    # TODO: PROTECT ALL FILE IO (including read_csv, like the line below); need
    # try execpts
    df = pd.read_csv(path)
    df = _wrangle_live(df)
    ch_course_ranges = ((100, 140), (280, 320)) # (outbound, inbound)
    sv_course_ranges = ((100, 160), (280, 340)) # (outbound, inbound)
    course_ranges = (ch_course_ranges, sv_course_ranges)
    ports = [None, None] # ch, sv
    # split data into Charleston and Savannah DataFrames based on latitude
    for i in range(len(ports)):
        ch_df = (df.Latitude >= 32.033)
        sv_df = (df.Latitude < 32.033)
        ports[i] = df[ch_df] if (i == 0) else df[sv_df]
        if not len(ports[i]):
            continue
        ports[i] = _course_behavior(ports[i], course_ranges[i])
        ports[i] = _add_vessel_class(ports[i])
        # remove unwanted blacklist vessels
        ports[i] = _filter_blacklisters(ports[i], blacklist)
        ports[i] = ports[i][["UTC", "Name", "VSPD kn",
                             "Course Behavior", "Class"]]
    return ports[0], ports[1] # ch, sv

def process_report(path):
    """Processes data from vessel movement report. Adds data from wind buoys,
    performs meeting and passing analysis. Creates other relevant columns.

    Args:
        path: Relative path to raw vessel movement report (CSV).

    Returns:
        Two pairs of two DataFrames cooresponding to the movement report.
        The first pair of DataFrames contains all vessel movements belonging to
        Charleston and Savannah, respectively. The second pair of DataFrames
        stores the vessel movement entries at which each vessel achieved
        its maximum speed. Again, the first DataFrame in the pair belongs to
        Charleston and the second DataFrame belongs to Savannah.
    """
    blacklist = [int(mmsi) for mmsi in open("../cache/blacklist.txt",
                                            "r").readlines()]
    df = pd.read_csv(path)
    df = _wrangle_vmr(df, {"DATETIME (UTC)": "Date/Time UTC", "NAME": "Name",
                           "LATITUDE": "Latitude", "LONGITUDE": "Longitude",
                           "SPEED": "VSPD kn", "COURSE": "Course", "HEADING":
                           "Heading", "AIS TYPE": "AIS Type"})
    ch_course_ranges = ((100, 140), (280, 320)) # (outbound, inbound)
    sv_course_ranges = ((100, 160), (280, 340)) # (outbound, inbound)
    # longitudinal channel midpoint for Charleston and Savannah respectively
    channel_midpoint = ((-79.74169), (-80.78522))
    course_ranges = (ch_course_ranges, sv_course_ranges)
    ports = [None, None] # ch, sv
    # Charleston NOAA wind buoy ID (41004)
    # Savannah NOAA wind buoy ID (41008)
    buoys = [{"41004":None}, {"41008":None}] # main wind buoys
    alt_buoys = [{"41008":None}, {"41004":None}] # alternate wind buoys
    # split data into Charleston and Savannah DataFrames based on latitude
    for i in range(len(ports)):
        ch_df = (df.Latitude >= 32.033)
        sv_df = (df.Latitude < 32.033)
        ports[i] = df[ch_df] if (i == 0) else df[sv_df]
        # if there is no vessel data on a given day (e.g. major holidays)
        # return empty DataFrames
        if not len(ports[i]):
            empty = pd.DataFrame({"Date/Time UTC":[], "Name":[], "MMSI":[],
                                  "Max Speed kn":[], "Mean Speed kn":[],
                                  "LOA ft":[], "Beam ft":[], "Class":[],
                                  "AIS Type":[], "Course":[], "Heading":[],
                                  "Course Behavior":[], "Yaw deg":[],
                                  "Effective Beam ft":[], "WDIR degT":[],
                                  "WSPD mph":[], "GST mph":[], "Buoy Source":[],
                                  "Location":[], "Latitude":[], "Longitude":[],
                                  "Transit":[], "% Channel Occupied":[]})
            ports[i] = [empty, empty]
            continue
        # initialize location column to Nearshore; compute Offshore locations
        ports[i].loc[:, "Location"] = "Nearshore"
        off_locs = ports[i][ports[i]["Longitude"] > channel_midpoint[i]].index
        offshore_indices = ports[i].index.isin(off_locs)
        ports[i].loc[offshore_indices, "Location"] = "Offshore"
        ports[i] = add_wind(ports, i, buoys, alt_buoys)
        ports[i] = _course_behavior(ports[i], course_ranges[i])
        ports[i] = _add_vessel_class(ports[i])
        # create yaw column based on difference between course and heading
        ports[i].loc[:, "Yaw deg"] = abs(ports[i].loc[:, "Course"] -
                                         ports[i].loc[:, "Heading"])
        # compute effective beam based on vessel beam, loa, and yaw
        eff_beam = []
        loa = ports[i]["LOA ft"].values
        beam = ports[i]["Beam ft"].values
        yaw = ports[i]["Yaw deg"].values
        for l in range(ports[i].shape[0]):
            # effective beam formula derived using trigonometry and geometry
            # of vessel positions
            eff_beam.append(round((math.cos(math.radians(90 - yaw[l])) *
                            loa[l]) + (math.cos(math.radians(yaw[l])) *
                            beam[l])))
        ports[i].loc[:, "Effective Beam ft"] = eff_beam
        ports[i].loc[:, "Effective Beam ft"] = ports[i].loc[:,
                                               "Effective Beam ft"].round(0)
        # remove unwanted blacklist vessels
        ports[i] = _filter_blacklisters(ports[i], blacklist)
        # create rounded DateTime column for meetpass analysis
        stamps = len(ports[i].loc[:, "Date/Time UTC"]) # number of timestamps
        round_times = [ports[i].loc[:, "Date/Time UTC"].iloc[ii].floor("Min")
                       for ii in range(stamps)]
        ports[i].loc[:, "rounded date"] = round_times
        # run meetpass analysis and create Transit column based on results
        mp = meetpass(ports[i])
        two_way = twoway(ports[i], mp)
        ports[i]["Transit"] = "One-way Transit"
        if not isinstance(two_way, type(None)):
            two_way_indices = ports[i].index.isin(two_way.index)
            ports[i]["Transit"][two_way_indices] = "Two-way Transit"
        # reset index to clear previous pandas manipulations
        ports[i] = ports[i].reset_index()
        ports[i] = _add_channel_occ(ports, i)
        # save current format of data as all_res to be used for all positions
        all_res = ports[i]
        # remove sections of channel where ships turn
        if i % 2:
            all_res = all_res[(all_res.Latitude <= 32.02838) &
                              (all_res.Latitude >= 31.9985) |
                              (all_res.Latitude <= 31.99183)]
        else:
            all_res = all_res[all_res.Latitude >= 32.667473]
        fold_res = _fold_vmr(ports, i)
        # return max and mean positional data in specified order
        # fold_res = fold_res[["Date/Time UTC", "Name", "MMSI", "Max Speed kn",
        #                      "Mean Speed kn", "LOA ft", "Beam ft",
        #                      "Class", "AIS Type", "Course", "Heading",
        #                      "Course Behavior", "Yaw deg", "Effective Beam ft",
        #                      "WDIR degT", "WSPD mph", "GST mph", "Buoy Source",
        #                      "Location", "Latitude", "Longitude", "Transit",
        #                      "% Channel Occupied"]]
        fold_res = fold_res.loc[:, ("Date/Time UTC", "Name", "MMSI", "Max Speed kn",
                             "Mean Speed kn", "LOA ft", "Beam ft",
                             "Class", "AIS Type", "Course", "Heading",
                             "Course Behavior", "Yaw deg", "Effective Beam ft",
                             "WDIR degT", "WSPD mph", "GST mph", "Buoy Source",
                             "Location", "Latitude", "Longitude", "Transit",
                             "% Channel Occupied")]
        # return positional data in specified order
        # all_res = all_res[["Name", "MMSI", "VSPD kn", "WSPD mph", "Transit",
        #                    "% Channel Occupied", "Yaw deg", "Effective Beam ft",
        #                    "LOA ft", "Beam ft", "Class", "AIS Type",
        #                    "Course", "Heading", "Course Behavior", "WDIR degT",
        #                    "GST mph", "Buoy Source", "Location", "Latitude",
        #                    "Longitude", "Date/Time UTC"]]
        all_res = all_res.loc[:, ("Name", "MMSI", "VSPD kn", "WSPD mph", "Transit",
                           "% Channel Occupied", "Yaw deg", "Effective Beam ft",
                           "LOA ft", "Beam ft", "Class", "AIS Type",
                           "Course", "Heading", "Course Behavior", "WDIR degT",
                           "GST mph", "Buoy Source", "Location", "Latitude",
                           "Longitude", "Date/Time UTC")]
        # save two copies of daily vmr for each port, one for all vessel
        # positions and one for maximum vessel speed positions
        ports[i] = [fold_res, all_res]
    return ports[0], ports[1] # ch, sv

report = process_report("../temp/2021-02-09.csv")

report[0][0]
