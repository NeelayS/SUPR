# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V. (MPG),
# acting on behalf of its Max Planck Institute for Intelligent Systems and the
# Max Planck Institute for Biological Cybernetics. All rights reserved.
#
# Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V. (MPG) is holder of all proprietary rights
# on this computer program. You can only use this computer program if you have closed a license agreement
# with MPG or you get the right to use the computer program from someone who is authorized to grant you that right.
# Any use of the computer program without a valid license is prohibited and liable to prosecution.
# Contact: ps-license@tuebingen.mpg.de
#
# Code Developed by:
# Ahmed A. A. Osman


import os

import numpy as np
import tensorflow as tf

from ..config import cfg


@tf.function
def quaternions_all(p):
    batch_size = tf.shape(p)[0]
    num_joints = tf.shape(p)[1]
    angle = tf.reshape(
        tf.sqrt(
            tf.clip_by_value(
                tf.reduce_sum(tf.square(p), 2),
                tf.constant(1e-16, dtype=tf.float32),
                tf.constant(1e16, dtype=tf.float32),
            ),
            name="angles",
        ),
        [batch_size, num_joints, 1],
    )
    norm_p = p / angle
    norm_p = tf.transpose(norm_p, [2, 0, 1])
    ####################################################################################################################
    tf_gathered_x = tf.gather(norm_p, 0)
    tf_gathered_y = tf.gather(norm_p, 1)
    tf_gathered_z = tf.gather(norm_p, 2)
    ####################################################################################################################
    sin_angle = tf.squeeze(tf.sin(angle / 2), axis=-1)
    cose_angle = tf.squeeze(tf.cos(angle / 2), axis=-1)
    ####################################################################################################################
    qx = tf_gathered_x * sin_angle
    qy = tf_gathered_y * sin_angle
    qz = tf_gathered_z * sin_angle
    qw = cose_angle
    norm_quat = tf.reshape(
        tf.stack([qx - 0, qy - 0, qz - 0, qw - 1], axis=2), [batch_size, -1]
    )
    ####################################################################################################################
    return norm_quat


@tf.function
def global_rigid_transformation(rot_mat, J, batch_size, num_joints):
    """
    TensorFlow implementation of the global rigid transformation.
    :param rot_mat: batch_size x num_joints x 3 x 3 tensor of the rotation matrices.
    :param J      : batch_size x num_joints x 3 tensor of 3D joints positions
    :param kintree_table: a 2D array encoding the body kinemenatic tree.
           First row is the index of the parent node, second row is the index of a child node.
    :return: result: batch_size x num_joints x 4 x 4 x tensors
    """
    kintree_table = cfg.kintree_table
    parent_nodes = kintree_table[0, 1:]
    Js = tf.cast(J, tf.float32) - tf.concat(
        [
            tf.zeros([batch_size, 1, 3], dtype=tf.float32),
            tf.gather(J, parent_nodes, axis=1),
        ],
        axis=1,
    )
    Js = tf.expand_dims(Js, axis=-1)
    T = tf.concat([tf.cast(rot_mat, tf.float32), Js], axis=-1)

    T = tf.concat(
        [
            T,
            tf.tile(
                tf.constant([[[[0.0, 0.0, 0.0, 1.0]]]], dtype=tf.float32),
                [batch_size, num_joints, 1, 1],
            ),
        ],
        axis=2,
    )
    T = tf.unstack(T, axis=1)
    results = {i: None for i in range(0, J.shape[1])}
    results[0] = T[0]

    for i in range(1, J.shape[1]):
        results[i] = tf.einsum("ijk,ikl->ijl", results[kintree_table[0, i]], T[i])
    results_global = tf.stack([results[i] for i in range(0, J.shape[1])], axis=1)

    Jt = tf.einsum(
        "ijkl,ijl->ijk",
        results_global,
        tf.concat(
            [J, tf.zeros([batch_size, num_joints, 1], dtype=tf.float32)], axis=-1
        ),
    )
    results = results_global - tf.concat(
        [
            tf.zeros([batch_size, num_joints, 4, 3], dtype=tf.float32),
            tf.expand_dims(Jt, axis=-1),
        ],
        axis=-1,
    )
    return results, results_global


@tf.function
def verts_core(pose, v, J, weights, kintree_table, batch_size, num_joints):
    """
    Core linear blend skinning function.
    :param pose: num_batches x num_joints x 3 rotation vectors.
    :param v: batch_size x num_vertices x 3 shaped verticies.
    :param J: batch_size x num_joints x 3 joint location.
    :param weights: num_vertices x num_joints.
    :param kintree_table: Kinematic tree 2 x num_joints.
    :param want_Jtr: Transformed joints location.
    :return: batch_size x num_vertices x 3 transformed vertices
    """
    rot_mat = tf_rodrigues(pose, batch_size, num_joints)
    A, A_global = global_rigid_transformation(rot_mat, J, batch_size, num_joints)

    A_weighted = tf.einsum("ijkl,mj->imkl", A, weights)

    rest_shape_h = tf.concat(
        [v, tf.ones([batch_size, 10475, 1], dtype=tf.float32)], axis=-1
    )
    v = (
        A_weighted[:, :, :, 0] * tf.expand_dims(rest_shape_h[:, :, 0], axis=-1)
        + A_weighted[:, :, :, 1] * tf.expand_dims(rest_shape_h[:, :, 1], axis=-1)
        + A_weighted[:, :, :, 2] * tf.expand_dims(rest_shape_h[:, :, 2], axis=-1)
        + A_weighted[:, :, :, 3] * tf.expand_dims(rest_shape_h[:, :, 3], axis=-1)
    )

    v = tf.slice(v, [0, 0, 0], [-1, -1, 3])
    Jtr = A_global[:, :, :3, 3]
    return v, Jtr


@tf.function
def tf_rodrigues(p, batch_size, num_joints):
    """
        Rodrigues representation of dimensions
        batch_size x number of joints x 3 x 3
    :param p:
    :return:
    """
    angles = tf.reshape(
        tf.sqrt(
            tf.clip_by_value(
                tf.reduce_sum(tf.square(p), 2),
                tf.constant(1e-16, dtype=tf.float32),
                tf.constant(1e16, dtype=tf.float32),
            ),
            name="angles",
        ),
        [batch_size, num_joints, 1],
    )
    norm_p = p / angles

    ppt = tf.einsum(
        "ijkl,ijlm->ijkm",
        tf.expand_dims(norm_p, axis=-1),
        tf.expand_dims(norm_p, axis=2),
    )
    rx, ry, rz = tf.unstack(norm_p, axis=2)
    rx = tf.reshape(rx, [batch_size, num_joints, 1, 1])
    ry = tf.reshape(ry, [batch_size, num_joints, 1, 1])
    rz = tf.reshape(rz, [batch_size, num_joints, 1, 1])
    zrs = tf.zeros([batch_size, num_joints, 1, 1], dtype=tf.float32)

    skewmat = tf.reshape(
        tf.concat([zrs, -rz, ry, rz, zrs, -rx, -ry, rx, zrs], axis=-1),
        [batch_size, num_joints, 3, 3],
    )
    cos_angles = tf.tile(tf.expand_dims(tf.cos(angles), axis=-1), [1, 1, 3, 3])
    sin_angles = tf.tile(tf.expand_dims(tf.sin(angles), axis=-1), [1, 1, 3, 3])

    R = (
        tf.multiply(
            cos_angles,
            tf.tile(
                tf.expand_dims(
                    tf.expand_dims(tf.eye(3, 3, dtype=tf.float32), axis=0), axis=0
                ),
                [batch_size, num_joints, 1, 1],
            ),
        )
        + tf.multiply((1 - cos_angles), ppt)
        + tf.multiply(sin_angles, skewmat)
    )
    return R


@tf.function
def lrotmin(p):
    """
    Tensorflow implementation of the lrotmin feature
    :param p: num_batches x num_joints x 3 tensor of angles.
    :return: num_batches x 9*num_joints tensor
    """

    batch_size = tf.shape(p)[0]
    num_joints = tf.shape(p)[1]
    p = tf.slice(p, [0, 1, 0], [-1, -1, -1])
    I = tf.tile(
        tf.expand_dims(tf.expand_dims(tf.eye(3, 3, dtype=tf.float32), axis=0), axis=0),
        [batch_size, num_joints - 1, 1, 1],
    )
    rotmat = tf.reshape(tf_rodrigues(p) - I, [batch_size, -1])
    return rotmat


class SUPR(object):
    def __init__(self, path_model, num_betas=10):

        if not os.path.exists(path_model):
            raise RuntimeError("Path does not exist %s" % (path_model))
        import numpy as np

        self.model = np.load(path_model, allow_pickle=True)[()]
        cfg.kintree_table = self.model["kintree_table"].astype(np.int32)
        self.num_betas = num_betas

    @tf.function
    def __call__(self, pose, betas, trans):
        batch_size = pose.shape[0]
        if cfg.data_type == "float32":
            dtype = tf.float32
        elif cfg.data_type == "float64":
            dtype = tf.float64
        elif cfg.data_type == "float16":
            dtype = tf.float16

        self.J_regressor = tf.constant(self.model["J_regressor"], dtype=dtype)
        self.posedirs = tf.constant(self.model["posedirs"], dtype=dtype)
        self.shapedirs = tf.constant(
            self.model["shapedirs"][:, :, : self.num_betas], dtype=dtype
        )
        self.weights = tf.constant(self.model["weights"], dtype=dtype)
        self.kintree_table = self.model["kintree_table"].astype(np.int32)
        self.f = self.model["f"]
        tf_v_template = tf.constant(
            np.tile(self.model["v_template"], [batch_size, 1, 1]), dtype=dtype
        )
        v_shaped = tf.add(
            tf.einsum("ijk,lk->lij", self.shapedirs, betas), tf_v_template
        )

        num_joints = int(self.J_regressor.shape[0] / 3)
        num_verts = int(v_shaped.shape[1])

        pose_feat = quaternions_all(tf.reshape(pose, (-1, num_joints, 3)))
        poseblendshapes = tf.einsum("ijk,lk->lij", self.posedirs, pose_feat)
        v_posed = v_shaped + poseblendshapes

        batch_size = int(v_shaped.shape[0])
        pad_v_shaped = tf.reshape(v_shaped, [-1, num_verts * 3])
        pad_v_shaped = tf.concat([pad_v_shaped, tf.ones((batch_size, 1))], axis=1)
        tf_J = tf.einsum("ji,ai->aj", self.J_regressor, pad_v_shaped)
        tf_J = tf.reshape(tf_J, [-1, num_joints, 3])

        result, Jtr = verts_core(
            tf.reshape(pose, (-1, num_joints, 3)),
            v_posed,
            tf_J,
            self.weights,
            self.kintree_table,
            batch_size,
            num_joints,
        )
        result = tf.add(
            result, tf.tile(tf.expand_dims(trans, axis=1), [1, num_verts, 1])
        )
        result.Jtr = tf.add(
            Jtr, tf.tile(tf.expand_dims(trans, axis=1), [1, num_joints, 1])
        )
        result.pose = pose
        result.trans = trans
        result.betas = betas
        return result
