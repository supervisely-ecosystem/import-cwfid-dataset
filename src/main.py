
import os, zipfile, yaml
import supervisely as sly
import sly_globals as g
import gdown
from supervisely.io.fs import get_file_name
from supervisely.imaging.image import read
import numpy as np
import cv2


def read_yaml(ann_path):
    with open(ann_path, "r") as stream:
        try:
            ann_json = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)
    return ann_json


def create_polygon(points_x, points_y):
    points = []
    for idx, x in enumerate(points_x):
        points.append(sly.PointLocation(points_y[idx], x))

    return sly.Polygon(points, interior=[])


def get_image_shape(img_path):
    im = read(img_path)

    return im.shape[0], im.shape[1]


def create_ann(img_path):
    labels = []

    height, width = get_image_shape(img_path)

    img_id = get_file_name(img_path).split('_')[0]

    mask_path = os.path.join(g.annotations_path, img_id + g.mask_suffix)
    mask_ann_gray = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)

    ann_path = os.path.join(g.annotations_path, img_id + g.ann_suffix)
    ann_json = read_yaml(ann_path)

    for ann in ann_json['annotation']:
        obj_class = g.meta.get_obj_class(ann['type'])
        points_x = ann['points']['x']
        points_y = ann['points']['y']

        if type(points_x) != list:  # skip one pixel annotation
            continue

        polygon = create_polygon(points_x, points_y)
        mask = np.zeros((height, width), dtype=np.uint8)
        polygon.draw(mask, 1)
        res_mask = mask_ann_gray + mask
        mask_bool = res_mask == g.name_to_index[ann['type']]
        bitmap = sly.Bitmap(mask_bool)
        label = sly.Label(bitmap, obj_class)
        labels.append(label)

    return sly.Annotation(img_size=(height, width), labels=labels)


def extract_zip():
    if zipfile.is_zipfile(g.archive_path):
        with zipfile.ZipFile(g.archive_path, 'r') as archive:
            archive.extractall(g.work_dir_path)
    else:
        g.logger.warn('Archive cannot be unpacked {}'.format(g.arch_name))
        g.my_app.stop()


@g.my_app.callback("import_minne_apple")
@sly.timeit
def import_minne_apple(api: sly.Api, task_id, context, state, app_logger):

    gdown.download(g.cwfid_url, g.archive_path, quiet=False)
    extract_zip()

    images_path = os.path.join(g.work_dir_path, g.folder_name, g.images_folder_name)
    g.annotations_path = os.path.join(g.work_dir_path, g.folder_name, g.annotation_folder_name)

    images_names = os.listdir(images_path)

    new_project = api.project.create(g.WORKSPACE_ID, g.project_name, change_name_if_conflict=True)
    api.project.update_meta(new_project.id, g.meta.to_json())

    new_dataset = api.dataset.create(new_project.id, g.dataset_name, change_name_if_conflict=True)

    progress = sly.Progress('Upload items', len(images_names), app_logger)
    for img_batch in sly.batched(images_names, batch_size=g.batch_size):

        img_pathes = [os.path.join(images_path, name) for name in img_batch]
        img_infos = api.image.upload_paths(new_dataset.id, img_batch, img_pathes)
        img_ids = [im_info.id for im_info in img_infos]

        anns = [create_ann(img_path) for img_path in img_pathes]
        api.annotation.upload_anns(img_ids, anns)

        progress.iters_done_report(len(img_batch))

    g.my_app.stop()


def main():
    sly.logger.info("Script arguments", extra={
        "TEAM_ID": g.TEAM_ID,
        "WORKSPACE_ID": g.WORKSPACE_ID
    })
    g.my_app.run(initial_events=[{"command": "import_minne_apple"}])


if __name__ == '__main__':
    sly.main_wrapper("main", main)
