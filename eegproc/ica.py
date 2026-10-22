"""Separate ICA decomposition, automatic proposal, and explicit application."""
import contextlib
import io
import mne
import numpy as np
from ._utils import _backend_logging
from .signal_ops import physical_rank
CLASSES = ("brain", "muscle", "eye", "heart", "line_noise", "channel_noise", "other")

def choose_components(probabilities, config):
    p = np.asarray(probabilities, float)
    if p.ndim != 2 or p.shape[1] != 7 or not np.isfinite(p).all() or np.any(p < 0) or not np.allclose(p.sum(1), 1, atol=1e-5):
        raise ValueError("ICLabel must return normalized seven-class probabilities")
    if config.ica_rule == 'class_max':
        # Original script uses equality to the maximum (ties count), not argmax().
        highest = p.max(axis=1)
        selected = (p[:, 2] == highest) | ((p[:, 0] <= .5) &
            np.any(p[:, [1, 4, 5]] == highest[:, None], axis=1))
    elif config.ica_rule == 'threshold':
        selected = (p[:, 1:6].max(1) >= config.artifact_threshold) & (p[:, 0] <= config.brain_probability_max)
    else:
        raise ValueError("ica_rule must be threshold or class_max")
    return np.flatnonzero(selected).tolist()


def _select_heart(model, training, probabilities, removed, ecg_data, config):
    """With ECG require correlation; without ECG use ICLabel alone. No implicit proxy."""
    candidates=[i for i in removed if probabilities[i,3]>=config.artifact_threshold
                and np.max(probabilities[i,[1,2,4,5]])<config.artifact_threshold]
    decisions=[]
    if not candidates:return removed,decisions
    scores=np.zeros(len(candidates))
    if ecg_data is not None:
        # Pearson sufficient statistics in blocks: no full IC time-series array.
        ecg_data=np.asarray(ecg_data,float)
        if ecg_data.ndim!=2 or not len(ecg_data) or ecg_data.shape[1]!=training.n_times or not np.isfinite(ecg_data).all():
            raise ValueError('ECG reference must match the valid ICA training samples')
        sx=np.zeros(len(candidates));sxx=sx.copy();sy=np.zeros(len(ecg_data));syy=sy.copy()
        sxy=np.zeros((len(candidates),len(ecg_data)));count=0
        for start in range(0,training.n_times,65536):
            stop=min(start+65536,training.n_times)
            x=model.get_sources(training,start=start,stop=stop).get_data(picks=candidates)
            y=ecg_data[:,start:stop]
            sx+=x.sum(1);sxx+=(x*x).sum(1);sy+=y.sum(1);syy+=(y*y).sum(1);sxy+=x@y.T;count+=stop-start
        denominator=np.sqrt(np.maximum(sxx-sx*sx/count,0)[:,None]*np.maximum(syy-sy*sy/count,0)[None,:])
        correlations=np.divide(sxy-sx[:,None]*sy[None,:]/count,denominator,out=np.zeros_like(sxy),where=denominator>0)
        scores=np.max(np.clip(np.abs(correlations),0,1),axis=1)
    removed=list(removed)
    for i,score in zip(candidates,scores):
        delete=ecg_data is None or score>=config.heart_min_ecg_correlation
        if not delete:removed.remove(i)
        decisions.append(dict(component_0based=i,heart_probability=float(probabilities[i,3]),
            brain_probability=float(probabilities[i,0]),ecg_available=ecg_data is not None,
            absolute_ecg_correlation=float(score) if ecg_data is not None else None,
            automatically_removed=bool(delete),rule='iclabel_and_ecg' if ecg_data is not None else 'iclabel_only_no_ecg'))
    return removed,decisions


def fit_ica(training, config, ecg_data=None):
    rank, rank_info = physical_rank(training.get_data())
    if config.rank_method == 'covariance':
        x = training.get_data() * 1e6
        rank = min(int(np.linalg.matrix_rank(x)), int((np.linalg.eigvalsh(np.cov(x, bias=True)) > 1e-7).sum()))
        rank_info = dict(method='min(matrix_rank, covariance_eigenvalues_above_1e-7_uV2)', covariance_threshold_uv2=1e-7)
    if rank < 2:
        raise ValueError("ICA training rank is less than two")
    log = io.StringIO()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log), _backend_logging():
        from mne_icalabel.iclabel import iclabel_label_components
        # Picard solves the extended-Infomax objective with these settings.
        fit_params = (dict(ortho=False, extended=True, tol=config.ica_tolerance)
            if config.ica_method == "picard" else dict(extended=True,l_rate=.001,
                w_change=config.ica_tolerance,n_small_angle=None))
        model = mne.preprocessing.ICA(n_components=rank, method=config.ica_method, random_state=config.seed,
            max_iter=config.ica_max_iter, fit_params=fit_params)
        model.fit(training, picks="eeg", reject_by_annotation=True, verbose="warning")
        probs = iclabel_label_components(training, model, inplace=True)
        removed = choose_components(probs, config)
        heart_decisions=[]
        if config.ica_rule == 'threshold':
            removed,heart_decisions=_select_heart(model,training,probs,removed,ecg_data,config)
        # A decomposition checkpoint never implies components were subtracted.
        model.exclude = []
        iterations = int(model.n_iter_)
    report = {"rank": rank, "rank_details": rank_info, "probabilities": np.asarray(probs).tolist(),
        "classes": list(CLASSES), "removed_components_0based": [],
        "automatic_proposal_0based": removed, "decision_status": "pending", "applied": False,
        "iterations": iterations, "iteration_limit_reached": iterations is not None and iterations >= config.ica_max_iter,
        "fit_samples": training.n_times, "samples_per_rank_squared": training.n_times / rank**2,
        "residual_pca_dimensions_retained": True,
        "heart_support_decisions":heart_decisions,
        "component_selection": {"method": config.ica_rule, "heart_policy": "ecg_if_available_else_iclabel" if config.ica_rule=='threshold' else 'not_selected_by_original_matlab_rule',
            "ecg_available": ecg_data is not None,
            "ecg_assistance_used": bool(ecg_data is not None and heart_decisions),
            "heart_min_ecg_correlation":config.heart_min_ecg_correlation if config.ica_rule=='threshold' else None,
            "artifact_classes": list(CLASSES[1:6]) if config.ica_rule=='threshold' else [CLASSES[j] for j in [1,2,4,5]],
            "artifact_threshold": config.artifact_threshold if config.ica_rule=='threshold' else None,
            "brain_probability_max": config.brain_probability_max if config.ica_rule=='threshold' else .5,
            "brain_guard_applies_to": list(CLASSES[1:6]) if config.ica_rule=='threshold' else [CLASSES[j] for j in [1,4,5]],
            "ties_included": config.ica_rule=='class_max'},
        "log": log.getvalue()}
    return model, report


def validate_exclude(indices, n_components):
    if indices is None:
        raise ValueError('An explicit component list is required; [] means keep all')
    indices=list(indices)
    if any(isinstance(i, (bool, np.bool_)) or not isinstance(i, (int,np.integer)) or not 0 <= i < n_components for i in indices):
        raise ValueError('ICA exclusions must be integer zero-based indices inside the fitted model')
    if len(indices) != len(set(indices)):
        raise ValueError('Duplicate ICA component index')
    return sorted(int(i) for i in indices)


def apply_ica(model, application, report, config, exclude=None):
    if report.get('applied'):
        raise ValueError('ICA has already been applied to this processing state')
    manual = exclude is not None or config.ica_mode == 'manual'
    selected = validate_exclude(exclude if exclude is not None else
        config.ica_exclude if manual else report['automatic_proposal_0based'], model.n_components_)
    model.exclude = selected
    clean = model.apply(application, exclude=selected, verbose='warning')
    report.update(removed_components_0based=selected, decision_status='manual' if manual else 'automatic',
        applied=True, review_author=config.review_author if manual else None,
        review_reason=config.review_reason if manual else None)
    return clean


def _fit_ica(training, application, config, ecg_data=None):
    """Legacy convenience call; staged engine uses fit_ica/apply_ica separately."""
    model, report = fit_ica(training, config, ecg_data)
    clean = apply_ica(model, application, report, config)
    return clean, model, report


