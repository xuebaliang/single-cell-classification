from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
import scSemiCluster_utils as utils
import numpy as np
import h5py
import scipy as sp
import pandas as pd
import scanpy.api as sc
from sklearn.metrics.cluster import contingency_matrix


def read_clean(data):
    assert isinstance(data, np.ndarray)
    if data.dtype.type is np.bytes_:
        data = utils.decode(data)
    if data.size == 1:
        data = data.flat[0]
    return data


def dict_from_group(group):
    assert isinstance(group, h5py.Group)
    d = utils.dotdict()
    for key in group:
        if isinstance(group[key], h5py.Group):
            value = dict_from_group(group[key])
        else:
            value = read_clean(group[key][...])
        d[key] = value
    return d


def read_data(filename, sparsify=False, skip_exprs=False):
    with h5py.File(filename, "r") as f:
        obs = pd.DataFrame(dict_from_group(f["obs"]), index=utils.decode(f["obs_names"][...]))
        var = pd.DataFrame(dict_from_group(f["var"]), index=utils.decode(f["var_names"][...]))
        uns = dict_from_group(f["uns"])
        if not skip_exprs:
            exprs_handle = f["exprs"]
            if isinstance(exprs_handle, h5py.Group):
                mat = sp.sparse.csr_matrix((exprs_handle["data"][...], exprs_handle["indices"][...],
                                               exprs_handle["indptr"][...]), shape=exprs_handle["shape"][...])
            else:
                mat = exprs_handle[...].astype(np.float32)
                if sparsify:
                    mat = sp.sparse.csr_matrix(mat)
        else:
            mat = sp.sparse.csr_matrix((obs.shape[0], var.shape[0]))
    return mat, obs, var, uns


def read_real(filename, batch = True):
    data_path = "./data/real/" + filename + "/data.h5"
    mat, obs, var, uns = read_data(data_path, sparsify=False, skip_exprs=False)
    if isinstance(mat, np.ndarray):
        X = np.array(mat)
    else:
        X = np.array(mat.toarray())
    cell_name = np.array(obs["cell_ontology_class"])
    if (cell_name == "").sum() > 0:
        cell_name[cell_name == ""] = "unknown_class"
    if batch == True:
        batch_name = np.array(obs["dataset_name"])
        return X, cell_name, batch_name
    else:
        return X, cell_name


def read_simu(dataname):
    data_path = "./data/simulation/" + dataname
    data_mat = h5py.File(data_path)
    x = np.array(data_mat["X"])
    y = np.array(data_mat["Y"])
    batch = np.array(data_mat["B"])
    return x, y, batch


def normalize(adata, highly_genes = None, size_factors=True, normalize_input=True, logtrans_input=True):
    sc.pp.filter_genes(adata, min_counts=10)
    sc.pp.filter_cells(adata, min_counts=1)
    if size_factors or normalize_input or logtrans_input:
        adata.raw = adata.copy()
    else:
        adata.raw = adata

    if size_factors:
        sc.pp.normalize_per_cell(adata)
        adata.obs['size_factors'] = adata.obs.n_counts / np.median(adata.obs.n_counts)
    else:
        adata.obs['size_factors'] = 1.0

    if logtrans_input:
        sc.pp.log1p(adata)

    if highly_genes != None:
        sc.pp.highly_variable_genes(adata, min_mean=0.0125, max_mean=3, min_disp=0.5, n_top_genes = highly_genes, subset=True)

    if normalize_input:
        sc.pp.scale(adata)

    return adata


def annotation(cellname_train, cellname_test, Y_pred_train, Y_pred_test):
    train_confusion_matrix = contingency_matrix(cellname_train, Y_pred_train)
    annotated_cluster = np.unique(Y_pred_train)[train_confusion_matrix.argmax(axis=1)]
    annotated_celltype = np.unique(cellname_train)
    annotated_score = np.max(train_confusion_matrix, axis=1) / np.sum(train_confusion_matrix, axis=1)
    annotated_celltype[(np.max(train_confusion_matrix, axis=1) / np.sum(train_confusion_matrix, axis=1)) < 0.5] = "unassigned"
    final_annotated_cluster = []
    final_annotated_celltype = []
    for i in np.unique(annotated_cluster):
        candidate_celltype = annotated_celltype[annotated_cluster == i]
        candidate_score = annotated_score[annotated_cluster == i]
        final_annotated_cluster.append(i)
        final_annotated_celltype.append(candidate_celltype[np.argmax(candidate_score)])
    annotated_cluster = np.array(final_annotated_cluster)
    annotated_celltype = np.array(final_annotated_celltype)

    succeed_annotated_train = 0
    succeed_annotated_test = 0
    test_annotation_label = np.array(["original versions for unassigned cell ontology types"] * len(cellname_test))
    for i in range(len(annotated_cluster)):
        succeed_annotated_train += (cellname_train[Y_pred_train == annotated_cluster[i]] == annotated_celltype[i]).sum()
        succeed_annotated_test += (cellname_test[Y_pred_test == annotated_cluster[i]] == annotated_celltype[i]).sum()
        test_annotation_label[Y_pred_test == annotated_cluster[i]] = annotated_celltype[i]
    annotated_train_accuracy = np.around(succeed_annotated_train / len(cellname_train), 4)
    total_overlop_test = 0
    for celltype in np.unique(cellname_train):
        total_overlop_test += (cellname_test == celltype).sum()
    annotated_test_accuracy = np.around(succeed_annotated_test / total_overlop_test, 4)
    test_annotation_label[test_annotation_label == "original versions for unassigned cell ontology types"] = "unassigned"
    return annotated_train_accuracy, annotated_test_accuracy, test_annotation_label