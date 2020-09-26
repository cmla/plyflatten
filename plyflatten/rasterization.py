# Copyright (C) 2019, David Youssefi (CNES) <david.youssefi@cnes.fr>


import ctypes
import os

import affine
import numpy as np
from numpy.ctypeslib import ndpointer

from plyflatten import utils

# TODO: This is kind of ugly. Cleaner way to do this is to update
# LD_LIBRARY_PATH, which we should do once we have a proper config file
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lib = ctypes.CDLL(os.path.join(parent_dir, "lib", "libplyflatten.so"))


def plyflatten(cloud, xoff, yoff, resolution, xsize, ysize, radius, sigma, std=False):
    """
    Projects a points cloud into the raster band(s) of a raster image

    Args:
        cloud: A nb_points x (2+nb_extra_columns) numpy array:
            | x0 y0 [z0 r0 g0 b0 ...] |
            | x1 y1 [z1 r1 g1 b1 ...] |
            | ...                     |
            | xN yN [zN rN gN bN ...] |
            x, y give positions of the points into the final raster, the "extra
            columns" give the values
        xoff, yoff: offset position (upper left corner) considering the georeferenced image
        resolution: resolution of the output georeferenced image
        xsize, ysize: size of the georeferenced image
        radius: controls the spread of the blob from each point
        sigma: radius of influence for each point (unit: pixel)
        std (bool): if True, return additional channels with standard deviations

    Returns;
        A numpy array of shape (ysize, xsize, n) where n is nb_extra_columns if
            std=False and 2*nb_extra_columns if std=True
    """
    nb_points, nb_extra_columns = cloud.shape[0], cloud.shape[1] - 2
    raster_shape = (xsize * ysize, nb_extra_columns)

    # Set expected args and return types
    lib.rasterize_cloud.argtypes = (
        ndpointer(dtype=ctypes.c_double, shape=np.shape(cloud)),
        ndpointer(dtype=ctypes.c_float, shape=raster_shape),
        ndpointer(dtype=ctypes.c_float, shape=raster_shape),
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_float,
    )

    # Call rasterize_cloud function from libplyflatten.so
    raster = np.zeros(raster_shape, dtype="float32")
    raster_std = np.zeros(raster_shape, dtype="float32")
    lib.rasterize_cloud(
        np.ascontiguousarray(cloud.astype(np.float64)),
        raster,
        raster_std,
        nb_points,
        nb_extra_columns,
        xoff,
        yoff,
        resolution,
        xsize,
        ysize,
        radius,
        sigma,
    )

    # Transform result into a numpy array
    raster = raster.reshape((ysize, xsize, nb_extra_columns))
    if std:
        raster_std = raster_std.reshape((ysize, xsize, nb_extra_columns))
        raster = raster.dstack((raster, raster_std))

    return raster


def plyflatten_from_plyfiles_list(
    clouds_list, resolution, radius=0, roi=None, sigma=None, std=False
):
    """
    Projects a points cloud into the raster band(s) of a raster image (points clouds as files)

    Args:
        clouds_list: list of cloud.ply files
        resolution: resolution of the georeferenced output raster file
        roi: region of interest: (xoff, yoff, xsize, ysize), compute plyextrema if None
        std (bool): if True, return additional channels with standard deviations

    Returns:
        raster: georeferenced raster
        profile: profile for rasterio
    """
    # read points clouds
    full_cloud = list()
    for cloud in clouds_list:
        cloud_data, _ = utils.read_3d_point_cloud_from_ply(cloud)
        full_cloud.append(cloud_data.astype(np.float64))

    full_cloud = np.concatenate(full_cloud)

    # region of interest (compute plyextrema if roi is None)
    if roi is not None:
        xoff, yoff, xsize, ysize = roi
    else:
        xx = full_cloud[:, 0]
        yy = full_cloud[:, 1]
        xmin = np.amin(xx)
        xmax = np.amax(xx)
        ymin = np.amin(yy)
        ymax = np.amax(yy)

        xoff = np.floor(xmin / resolution) * resolution
        xsize = int(1 + np.floor((xmax - xoff) / resolution))

        yoff = np.ceil(ymax / resolution) * resolution
        ysize = int(1 - np.floor((ymin - yoff) / resolution))

    # The copy() method will reorder to C-contiguous order by default:
    full_cloud = full_cloud.copy()
    sigma = float("inf") if sigma is None else sigma
    raster = plyflatten(full_cloud, xoff, yoff, resolution, xsize, ysize, radius, sigma, std)

    crs, crs_type = utils.crs_from_ply(clouds_list[0])
    crs_proj = utils.rasterio_crs(utils.crs_proj(crs, crs_type))

    # construct profile dict
    profile = dict()
    profile["tiled"] = True
    profile["compress"] = "deflate"
    profile["predictor"] = 2
    profile["nodata"] = float("nan")
    profile["crs"] = crs_proj
    profile["transform"] = affine.Affine(resolution, 0.0, xoff, 0.0, -resolution, yoff)

    return raster, profile
