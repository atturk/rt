import pytest
import yaml

from rt.core.config import RTConfig, classifier_job, load_config
from rt.services.classifier_settings import write_classifier


def test_only_images_get_new_default():
    assert classifier_job(RTConfig(), 'images').threshold == .7
    assert classifier_job(RTConfig(), 'relevance').threshold == .8


@pytest.mark.parametrize('old,expected', [(.8, .7), (.65, .65), (.9, .9), (None, .7)])
def test_saved_threshold_migrates_once_and_preserves_user_choices(tmp_path, old, expected):
    path = tmp_path / 'general.yaml'
    images = {'mode': 'manual', 'threshold': old}
    data = {'recall': {'custom_types': []}, 'classifier': {'jobs': {'images': images}}}
    path.write_text(yaml.safe_dump(data))
    assert classifier_job(load_config(str(path)), 'images').threshold == expected
    saved = yaml.safe_load(path.read_text())
    assert saved['_migrations']['images_threshold_07'] is True
    # Come il salvataggio dalle impostazioni: il marker resta e 0,8 è ora una scelta.
    cfg = load_config(str(path))
    cfg.classifier.jobs['images'].threshold = .8
    write_classifier(saved, cfg.classifier)
    path.write_text(yaml.safe_dump(saved))
    assert classifier_job(load_config(str(path)), 'images').threshold == .8
