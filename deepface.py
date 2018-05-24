import logging
import os
import pickle
import sys
import cv2
import numpy as np

import fire
from sklearn.metrics import roc_curve
from tqdm import tqdm
import matplotlib.pyplot as plt

from confs.conf import DeepFaceConfs
from detectors.detector_dlib import FaceDetectorDlib
from recognizers.recognizer_vgg import FaceRecognizerVGG
from utils.common import get_roi
from utils.visualization import draw_bboxs

logger = logging.getLogger('DeepFace')
logger.setLevel(logging.INFO if int(os.environ.get('DEBUG', 0)) == 0 else logging.DEBUG)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')
ch.setFormatter(formatter)
logger.handlers = []
logger.addHandler(ch)


class DeepFace:
    def __init__(self):
        self.detector = None
        self.recognizer = None

    def set_detector(self, detector):
        if self.detector is not None and self.detector.name() == detector:
            return
        logger.debug('set_detector old=%s new=%s' % (self.detector, detector))
        if detector == FaceDetectorDlib.NAME:
            self.detector = FaceDetectorDlib()

    def set_recognizer(self, recognizer):
        if self.recognizer is not None and self.recognizer.name() == recognizer:
            return
        logger.debug('set_recognizer old=%s new=%s' % (self.recognizer, recognizer))
        if recognizer == FaceRecognizerVGG.NAME:
            self.recognizer = FaceRecognizerVGG()

    def blackpink(self, visualize=True):
        imgs = ['./samples/blackpink/blackpink%d.jpg' % (i+1) for i in range(7)]
        for img in imgs:
            self.run(image=img, visualize=visualize)

    def run(self, detector=FaceDetectorDlib.NAME, recognizer=FaceRecognizerVGG.NAME, image='./samples/ak.jpg', visualize=False):
        self.set_detector(detector)
        self.set_recognizer(recognizer)

        if isinstance(image, str):
            logger.debug('read image, path=%s' % image)
            npimg = cv2.imread(image, cv2.IMREAD_COLOR)
        elif isinstance(image, np.ndarray):
            npimg = image
        else:
            logger.error('Argument image should be str or ndarray. image=%s' % str(image))
            sys.exit(-1)

        if npimg is None:
            logger.error('image can not be read, path=%s' % image)
            sys.exit(-1)

        logger.debug('run face detection+ %dx%d' % (npimg.shape[1], npimg.shape[0]))
        faces = self.detector.detect(npimg)
        logger.debug('run face detection-')

        if recognizer:
            rois = []
            for face in faces:
                # roi = npimg[face.y:face.y+face.h, face.x:face.x+face.w, :]
                roi = get_roi(npimg, face)
                if int(os.environ.get('DEBUG_SHOW', 0)) == 1:
                    cv2.imshow('roi', roi)
                    cv2.waitKey(0)
                rois.append(roi)

            if len(rois) > 0:
                logger.debug('run face recognition+')
                result = self.recognizer.detect(rois)
                logger.debug('run face recognition-')
                for face_idx, face in enumerate(faces):
                    face.face_feature = result['feature'][face_idx]
                    name, score = result['name'][face_idx][0]
                    if score < DeepFaceConfs.get()['recognizer']['score_th']:
                        continue
                    face.face_name = name
                    face.face_score = score

        img = draw_bboxs(np.copy(npimg), faces)
        cv2.imwrite('result.jpg', img)
        if visualize and visualize not in ['false', 'False']:
            cv2.imshow('DeepFace', img)
            cv2.waitKey(0)

        return faces

    def save_features(self):
        # TODO : implemented
        name_paths = [
            ('jisoo', './samples/blackpink/blackpink_js1.jpg'),
            ('jennie', './samples/blackpink/blackpink_jn1.jpg'),
            ('lisa', './samples/blackpink/blackpink_lisa1.jpg'),
            ('rose', './samples/blackpink/blackpink_rose1.jpg'),
        ]
        features = {}
        for name, path in name_paths:
            faces = self.run(image=path)
            features[name] = faces[0].face_feature

        import pickle
        with open('db.pkl', 'wb') as f:
            pickle.dump(features, f, pickle.HIGHEST_PROTOCOL)

    def test_lfw(self, set='test', model='baseline', visualize=True):
        if set is 'train':
            pairfile = 'pairsDevTrain.txt'
        else:
            pairfile = 'pairsDevTest.txt'
        lfw_path = DeepFaceConfs.get()['dataset']['lfw']
        path = os.path.join(lfw_path, pairfile)
        with open(path, 'r') as f:
            lines = f.readlines()[1:]

        pairs = []
        for line in lines:
            elms = line.split()
            if len(elms) == 3:
                pairs.append((elms[0], int(elms[1]), elms[0], int(elms[2])))
            elif len(elms) == 4:
                pairs.append((elms[0], int(elms[1]), elms[2], int(elms[3])))
            else:
                logger.warning('line should have 3 or 4 elements, line=%s' % line)

        logger.info('pair length=%d' % len(pairs))
        test_result = []    # score, label(1=same)
        for name1, idx1, name2, idx2 in tqdm(pairs):
            img1_path = os.path.join(lfw_path, name1, '%s_%04d.jpg' % (name1, idx1))
            img2_path = os.path.join(lfw_path, name2, '%s_%04d.jpg' % (name2, idx2))
            img1 = cv2.imread(img1_path, cv2.IMREAD_COLOR)
            img2 = cv2.imread(img2_path, cv2.IMREAD_COLOR)

            if img1 is None:
                logger.warning('image not read, path=%s' % img1_path)
            if img2 is None:
                logger.warning('image not read, path=%s' % img2_path)

            result1 = self.run(image=img1)
            result2 = self.run(image=img2)

            if len(result1) == 0:
                logger.warning('face not detected, name=%s(%d)! %s(%d)' % (name1, idx1, name2, idx2))
                test_result.append((0.0, name1 == name2))
                continue
            if len(result2) == 0:
                logger.warning('face not detected, name=%s(%d) %s(%d)!' % (name1, idx1, name2, idx2))
                test_result.append((0.0, name1 == name2))
                continue

            feat1 = result1[0].face_feature
            feat2 = result2[0].face_feature
            similarity = np.dot(feat1 / np.linalg.norm(feat1, 2), feat2 / np.linalg.norm(feat2, 2))
            test_result.append((similarity, name1 == name2))

        # calculate accuracy
        accuracy = sum([label == (score > 0.78) for score, label in test_result]) / float(len(test_result))
        logger.info('accuracy=%.8f' % accuracy)

        # ROC Curve, AUC
        tps = []
        fps = []
        accuracy0 = []
        accuracy1 = []
        acc_th = []

        for th in range(0, 100, 5):
            th = th / 100.0
            tp = 0
            tn = 0
            fp = 0
            fn = 0
            for score, label in test_result:
                if score >= th and label == 1:
                    tp += 1
                elif score >= th and label == 0:
                    fp += 1
                elif score < th and label == 0:
                    tn += 1
                elif score < th and label == 1:
                    fn += 1
            tpr = tp / (tp + fn + 1e-12)
            fpr = fp / (fp + tn + 1e-12)
            tps.append(tpr)
            fps.append(fpr)
            accuracy0.append(tn / (tn + fp + 1e-12))
            accuracy1.append(tp / (tp + fn + 1e-12))
            acc_th.append(th)

        fpr, tpr, thresh = roc_curve([x[1] for x in test_result], [x[0] for x in test_result])
        fnr = 1 - tpr
        eer = fnr[np.nanargmin(np.absolute((fnr - fpr)))]
        logger.info('1-eer=%.4f' % (1.0 - eer))

        if visualize in [True, 'True', 'true', 1, '1']:
            fig = plt.figure()
            a = fig.add_subplot(1, 2, 1)
            plt.title('Experiment on LFW')
            plt.plot(fpr, tpr, label='%s(%.4f)' % (model, 1-eer))    # TODO : label

            plt.xlim([0.0, 1.0])
            plt.ylim([0.0, 1.05])
            plt.xlabel('False Positive Rate')
            plt.ylabel('True Positive Rate')
            a.legend()
            a.set_title('Receiver operating characteristic')

            a = fig.add_subplot(1, 2, 2)
            plt.plot(accuracy0, acc_th, label='Accuracy_diff')
            plt.plot(accuracy1, acc_th, label='Accuracy_same')
            plt.xlim([0.0, 1.0])
            plt.ylim([0.0, 1.05])
            a.legend()
            a.set_title('%s : TP, TN' % model)

            plt.show()
            plt.draw()
            fig.savefig('./etc/roc.png', dpi=300)

        with open('./etc/test_lfw.pkl', 'rb') as f:
            results = pickle.load(f)

        with open('./etc/test_lfw.pkl', 'wb') as f:
            results[model] = {
                'fpr': fpr,
                'tpr': tpr,
                'acc_th': acc_th,
                'accuracy0': accuracy0,
                'accuracy1': accuracy1,
                'eer': eer
            }
            pickle.dump(results, f, pickle.HIGHEST_PROTOCOL)

        return 1.0 - eer


if __name__ == '__main__':
    fire.Fire(DeepFace)
