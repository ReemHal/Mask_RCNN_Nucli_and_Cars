# -*- coding: utf-8 -*-
"""nucli.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1l8___khY3vVKn7eCK7h5i1uGTHVt175O
"""

"""
Mask R-CNN
Train on the Kaggle's Nucli dataset.

Reem Al-Halimi
------------------------------------------------------------

Based on Waleed Abdulla's balloon Mask R-CNN sample scripts.

Copyright (c) 2018 Matterport, Inc.
Licensed under the MIT License (see LICENSE for details)
Written by Waleed Abdulla

------------------------------------------------------------

Usage: import the module (see Jupyter notebooks for examples), or run from
       the command line as such:

    # Train a new model starting from pre-trained COCO weights
    python3 nucli.py train --dataset=/path/to/nucli/dataset --weights=coco

    # Resume training a model that you had trained earlier
    python3 nucli.py train --dataset=/path/to/nucli/dataset --weights=last

    # Train a new model starting from ImageNet weights
    python3 nucli.py train --dataset=/path/to/nucli/dataset --weights=imagenet

    # Apply color splash to an image
    python3 nucli.py splash --weights=/path/to/weights/file.h5 --image=<URL or path to file>

    # Apply color splash to video using the last weights you trained
    python3 nucli.py splash --weights=last --video=<URL or path to file>
"""

import os
import sys
import json
import datetime
import numpy as np
import cv2
import skimage.draw
from sklearn.model_selection import train_test_split
from tqdm import *

# Root directory of the project
ROOT_DIR = '/content/drive/Kaggle/Mask_RCNN-master' #os.getcwd()
if ROOT_DIR.endswith("samples/nucli"):
    # Go up two levels to the repo root
    ROOT_DIR = os.path.dirname(os.path.dirname(ROOT_DIR))

# Import Mask RCNN
sys.path.append(ROOT_DIR)
from config import Config
import utils
import model as modellib

# Path to trained weights file
COCO_WEIGHTS_PATH = os.path.join(ROOT_DIR, "mask_rcnn_coco.h5")

# Directory to save logs and model checkpoints, if not provided
# through the command line argument --logs
DEFAULT_LOGS_DIR = os.path.join(ROOT_DIR, "logs")

############################################################
#  Configurations
############################################################


class NucliConfig(Config):
    """Configuration for training on the toy  dataset.
    Derives from the base Config class and overrides some values.
    """
    # Give the configuration a recognizable name
    NAME = "nucli"

    # We use a GPU with 12GB memory, which can fit two images.
    # Adjust down if you use a smaller GPU.
    IMAGES_PER_GPU = 2

    # Number of classes (including background)
    NUM_CLASSES = 1 + 1  # Background + baloon

    # Number of training steps per epoch
    STEPS_PER_EPOCH = 100

    # Skip detections with < 90% confidence
    DETECTION_MIN_CONFIDENCE = 0.9

    # Input image resing
    # Images are resized such that the smallest side is >= IMAGE_MIN_DIM and
    # the longest side is <= IMAGE_MAX_DIM. In case both conditions can't
    # be satisfied together the IMAGE_MAX_DIM is enforced.
    IMAGE_MIN_DIM = 800
    IMAGE_MAX_DIM = 1024

############################################################
#  Dataset
############################################################

class NucliDataset(utils.Dataset):

  def __int__(self, dataset_dict, *args, **kwargs):
      super(NucliDataset, self).__init__(*args, **kwargs)
      self.dataset_dict = dataset_dict

  def _adjust_gamma(self, image, gamma=1.0):
        # build a lookup table mapping the pixel values [0, 255] to
        # their adjusted gamma values
        # Source: https://www.pyimagesearch.com/2015/10/05/opencv-gamma-correction/

        invGamma = 1.0 / gamma
        table = np.array([((i / 255.0) ** invGamma) * 255
          for i in np.arange(0, 256)]).astype("uint8")

        # apply gamma correction using the lookup table
        return cv2.LUT(image, table)

  def load_image(self, image_id, image_path=None, gamma=2.0): #, img_h, img_w, img_ch, resize_mode='constant'):
        """Load the specified image and return a [H,W,3] Numpy array.
        """
        if image_path == None:
          image_path = os.path.join( dataset.image_info[image_id]["path"],  'images/', str(dataset.image_info[image_id]["id"])+'.png')
        # Load image
        image = skimage.io.imread(image_path)
        img_shape = [image.shape[0], image.shape[1]]
        #img = resize(img, (img_h, img_w), mode=resize_mode, preserve_range=True)
        # If grayscale. Convert to RGB for consistency.
        if image.ndim != 3:
            image = skimage.color.gray2rgb(image)
        elif (len(image.shape)==3) and (image.shape[2]==4):
            image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB) #skimage.color.rgba2rgb(image) #remove the alpha channel
            image = self._adjust_gamma(image, gamma)

        image = np.array(image, dtype=np.uint8)

        return image

  def load_nucli(self, dataset_dir, subset, image_ids=None):
        """Load a subset of the nucli dataset.
        dataset_dir: Root directory of the dataset.
        subset: Subset to load: train or val
        """
        # Add classes. We have only one class to add.
        self.add_class("nucli", 1, "nucli")

        # Train or validation dataset?
        assert subset in ["train", "test", "test2"]
        dataset_dir = os.path.join(dataset_dir, self.dataset_dict[subset])

        # Add images
        # Get train and test IDs
        # if no preset image_ids list is given, read all image ids form the dataset dir
        if image_ids == None:
            image_ids = os.listdir(dataset_dir)
        for id_ in tqdm(image_ids, total=len(image_ids), unit="images"):
            if os.path.isdir(os.path.join(dataset_dir,id_)):
                image_path = os.path.join(dataset_dir, id_ ) # image path is the directory containing the image and its masks
                full_path = os.path.join(image_path, 'images/', id_+'.png')
                image = self.load_image(id_, image_path=full_path)
                height= image.shape[0]
                width = image.shape[1]

                self.add_image(
                    "nucli",
                    image_id=id_,  # use directory name (i.e. image name without teh .png extension) as a unique image id
                    path=image_path, # image path is the directory comtaining the image and its masks
                    width=width, height=height)

  def load_mask(self, image_id):
        """Generate instance masks for an image.
        Returns:
          masks: A bool array of shape [height, width, instance count] with
              one mask per instance.
          class_ids: a 1D array of class IDs of the instance masks.
        """
        # If not a nucli dataset image, delegate to parent class.
        image_info = self.image_info[image_id]
        if image_info["source"] != "nucli":
            return super(self.__class__, self).load_mask(image_id)

        # Convert polygons to a bitmap mask of shape
        # [height, width, instance_count]
        info = self.image_info[image_id]
        mask_files = os.listdir(self.image_info[image_id]["path"]+'/masks/')
        num_masks = len(mask_files)
        mask = np.zeros([info["height"], info["width"], num_masks],
                        dtype=np.uint8)
        i = 0
        for file_id_ in mask_files:
            # Get indexes of pixels inside the polygon and set them to 1
            mask_path = self.image_info[image_id]["path"]
            mask_instance = skimage.io.imread(mask_path + '/masks/'+ file_id_)
            height = mask_instance[0]
            width = mask_instance[1]
            mask[:, :, i] = mask_instance
            i = i + 1

        # Return mask, and array of class IDs of each instance. Since we have
        # one class ID only, we return an array of 1s
        return mask, np.ones([mask.shape[-1]], dtype=np.int32)

  def image_reference(self, image_id):
        """Return the path of the image."""
        info = self.image_info[image_id]
        if info["source"] == "nucli":
            return info["path"]
        else:
            super(self.__class__, self).image_reference(image_id)


def train(model):
    """Train the model."""

    dataset_dict = {"train":"stage1_train", "test":"stage1_test", "test2":"stage1_test 2"}

    # Get the list of image IDs
    dataset_dir = os.path.join(args.dataset, dataset_dict["train"])
    image_ids = os.listdir(dataset_dir)
    #split ids into training and validation sets
    train_image_ids, val_image_ids = train_test_split(image_ids, shuffle=True, test_size=0.25)

    # Training dataset.
    print("Creating training set..")
    dataset_train = NucliDataset(dataset_dict)
    dataset_train.load_nucli(args.dataset, "train", image_ids= train_image_ids)
    dataset_train.prepare()

    # Validation dataset (the images to be used for validation are under the same dir as the training images)
    print("Creating validation set..")
    dataset_val = NucliDataset(dataset_dict)
    dataset_val.load_nucli(args.dataset, "train", val_image_ids)
    dataset_val.prepare()

    # *** This training schedule is an example. Update to your needs ***
    # Since we're using a very small dataset, and starting from
    # COCO trained weights, we don't need to train too long. Also,
    # no need to train all layers, just the heads should do it.
    print("Training network heads")
    model.train(dataset_train, dataset_val,
                learning_rate=config.LEARNING_RATE,
                epochs=30,
                layers='heads')


def color_splash(image, mask):
    """Apply color splash effect.
    image: RGB image [height, width, 3]
    mask: instance segmentation mask [height, width, instance count]

    Returns result image.
    """
    # Make a grayscale copy of the image. The grayscale copy still
    # has 3 RGB channels, though.
    gray = skimage.color.gray2rgb(skimage.color.rgb2gray(image)) * 255
    # We're treating all instances as one, so collapse the mask into one layer
    mask = (np.sum(mask, -1, keepdims=True) >= 1)
    # Copy color pixels from the original color image where mask is set
    if mask.shape[0] > 0:
        splash = np.where(mask, image, gray).astype(np.uint8)
    else:
        splash = gray
    return splash


def detect_and_color_splash(model, image_path=None, video_path=None):
    assert image_path or video_path

    # Image or video?
    if image_path:
        # Run model detection and generate the color splash effect
        print("Running on {}".format(args.image))
        # Read image
        image = skimage.io.imread(args.image)
        # Detect objects
        r = model.detect([image], verbose=1)[0]
        # Color splash
        splash = color_splash(image, r['masks'])
        # Save output
        file_name = "splash_{:%Y%m%dT%H%M%S}.png".format(datetime.datetime.now())
        skimage.io.imsave(file_name, splash)
    elif video_path:
        import cv2
        # Video capture
        vcapture = cv2.VideoCapture(video_path)
        width = int(vcapture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(vcapture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = vcapture.get(cv2.CAP_PROP_FPS)

        # Define codec and create video writer
        file_name = "splash_{:%Y%m%dT%H%M%S}.avi".format(datetime.datetime.now())
        vwriter = cv2.VideoWriter(file_name,
                                  cv2.VideoWriter_fourcc(*'MJPG'),
                                  fps, (width, height))

        count = 0
        success = True
        while success:
            print("frame: ", count)
            # Read next image
            success, image = vcapture.read()
            if success:
                # OpenCV returns images as BGR, convert to RGB
                image = image[..., ::-1]
                # Detect objects
                r = model.detect([image], verbose=0)[0]
                # Color splash
                splash = color_splash(image, r['masks'])
                # RGB -> BGR to save image to video
                splash = splash[..., ::-1]
                # Add image to video writer
                vwriter.write(splash)
                count += 1
        vwriter.release()
    print("Saved to ", file_name)

############################################################
#  Training
############################################################

if __name__ == '__main__':
    import argparse

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Train Mask R-CNN to detect balloons.')
    parser.add_argument("command",
                        metavar="<command>",
                        help="'train' or 'splash'")
    parser.add_argument('--dataset', required=False,
                        metavar="/path/to/balloon/dataset/",
                        help='Directory of the Balloon dataset')
    parser.add_argument('--weights', required=True,
                        metavar="/path/to/weights.h5",
                        help="Path to weights .h5 file or 'coco'")
    parser.add_argument('--logs', required=False,
                        default=DEFAULT_LOGS_DIR,
                        metavar="/path/to/logs/",
                        help='Logs and checkpoints directory (default=logs/)')
    parser.add_argument('--image', required=False,
                        metavar="path or URL to image",
                        help='Image to apply the color splash effect on')
    parser.add_argument('--video', required=False,
                        metavar="path or URL to video",
                        help='Video to apply the color splash effect on')
    args = parser.parse_args()

    # Validate arguments
    if args.command == "train":
        assert args.dataset, "Argument --dataset is required for training"
    elif args.command == "splash":
        assert args.image or args.video,\
               "Provide --image or --video to apply color splash"

    print("Weights: ", args.weights)
    print("Dataset: ", args.dataset)
    print("Logs: ", args.logs)

    # Configurations
    if args.command == "train":
        config = NucliConfig()
    else:
        class InferenceConfig(NucliConfig):
            # Set batch size to 1 since we'll be running inference on
            # one image at a time. Batch size = GPU_COUNT * IMAGES_PER_GPU
            GPU_COUNT = 1
            IMAGES_PER_GPU = 1
        config = InferenceConfig()
    config.display()

    # Create model
    if args.command == "train":
        model = modellib.MaskRCNN(mode="training", config=config,
                                  model_dir=args.logs)
    else:
        model = modellib.MaskRCNN(mode="inference", config=config,
                                  model_dir=args.logs)

    # Select weights file to load
    if args.weights.lower() == "coco":
        weights_path = COCO_WEIGHTS_PATH
        # Download weights file
        if not os.path.exists(weights_path):
            utils.download_trained_weights(weights_path)
    elif args.weights.lower() == "last":
        # Find last trained weights
        weights_path = model.find_last()[1]
    elif args.weights.lower() == "imagenet":
        # Start from ImageNet trained weights
        weights_path = model.get_imagenet_weights()
    else:
        weights_path = args.weights

    # Load weights
    print("Loading weights ", weights_path)
    if args.weights.lower() == "coco":
        # Exclude the last layers because they require a matching
        # number of classes
        model.load_weights(weights_path, by_name=True, exclude=[
            "mrcnn_class_logits", "mrcnn_bbox_fc",
            "mrcnn_bbox", "mrcnn_mask"])
    else:
        model.load_weights(weights_path, by_name=True)

    # Train or evaluate
    if args.command == "train":
        print("setting up for training...")
        train(model)
    elif args.command == "splash":
        print("Splashing...")
        detect_and_color_splash(model, image_path=args.image,
                                video_path=args.video)
    else:
        print("'{}' is not recognized. "
              "Use 'train' or 'splash'".format(args.command))
