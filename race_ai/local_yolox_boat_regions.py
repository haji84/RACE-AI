"""Separate offline YOLOX_s COCO boat candidates, never verified hull IDs.

Based on OpenCV Zoo Apache-2.0 model/demo at pinned commit
ea593dd89b88d4b3978273a16f0d8cfe93d2e3ea. See models/YOLOX_LICENSE.
"""
import hashlib
import math
from pathlib import Path

import cv2
import numpy as np

from .core import SourceError
from .video_number_marks import geometry
from .local_boat_regions import pixels_required

MODEL_NAME='object_detection_yolox_2022nov.onnx'
MODEL_BYTES=35858002
MODEL_SHA256='c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063'

def require(value):
    if not value:raise SourceError('LOCAL_YOLOX_BOAT_CONTRACT_INVALID')

def resize_shape(width,height):
    geometry(width,height,[])
    scale=min(640/width,640/height)
    return max(1,int(width*scale)),max(1,int(height*scale))

def decode_yolox_regions(output,*,width,height,exclusions=None):
    try:return _decode(output,width,height,[] if exclusions is None else exclusions)
    except SourceError:raise
    except Exception:raise SourceError('LOCAL_YOLOX_BOAT_CONTRACT_INVALID') from None

def _decode(output,width,height,exclusions):
    masks=geometry(width,height,exclusions);rw,rh=resize_shape(width,height)
    require(type(output) is np.ndarray and output.dtype==np.float32 and output.shape==(1,8400,85)
            and np.isfinite(output).all() and np.all((output[:,:,4:]>=0)&(output[:,:,4:]<=1)))
    values=output[0];scores=values[:,4]*values[:,13]
    selected=np.flatnonzero((values[:,5:].argmax(axis=1)==8)&(scores>=.5))
    proposed=[]
    for i in selected[np.argsort(-scores[selected],kind='stable')[:256]]:
        if i<6400:stride,side,j=8,80,int(i)
        elif i<8000:stride,side,j=16,40,int(i)-6400
        else:stride,side,j=32,20,int(i)-8000
        dx,dy,logw,logh=map(float,values[i,:4])
        require(abs(logw)<=32 and abs(logh)<=32)
        cx,cy=(dx+j%side)*stride,(dy+j//side)*stride
        bw,bh=math.exp(logw)*stride,math.exp(logh)*stride
        x1,y1=max(0.,(cx-bw/2)*width/rw),max(0.,(cy-bh/2)*height/rh)
        x2,y2=min(float(width),(cx+bw/2)*width/rw),min(float(height),(cy+bh/2)*height/rh)
        # Existing crop OCR requires at least one image pixel in each axis.
        if x2-x1<1 or y2-y1<1:continue
        if any(x1<a+c and a<x2 and y1<b+d and b<y2 for a,b,c,d in masks):continue
        proposed.append(dict(box=[x1,y1,x2-x1,y2-y1],confidence=float(scores[i])))
    kept=[]
    for r in proposed:
        x,y,w,h=r['box'];overlap=False
        for old in kept:
            a,b,c,d=old['box']
            area=max(0.,min(x+w,a+c)-max(x,a))*max(0.,min(y+h,b+d)-max(y,b))
            if area/(w*h+c*d-area)>.5:overlap=True;break
        if not overlap:kept.append(r)
        if len(kept)==12:break
    return dict(schema_version='local-yolox-boat-regions/v1',regions=kept,
                class_scope='GENERIC_COCO_BOAT_CANDIDATE',boat_identity='UNVERIFIED',
                world_calibration='UNVERIFIED',prediction_eligible=False,boat_features=[])

class LocalYoloXBoatRegions:
    def __init__(self,*,model_path=None):
        try:
            path=Path(model_path) if model_path is not None else Path(__file__).parent/'models'/MODEL_NAME
            require(path.is_file() and path.stat().st_size==MODEL_BYTES)
            raw=path.read_bytes();require(len(raw)==MODEL_BYTES and hashlib.sha256(raw).hexdigest()==MODEL_SHA256)
            self.net=cv2.dnn.readNetFromONNX(np.frombuffer(raw,dtype=np.uint8))
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except SourceError:raise
        except Exception:raise SourceError('LOCAL_YOLOX_BOAT_RUNTIME_UNAVAILABLE') from None

    def __call__(self,pixels,*,exclusions=None):
        try:
            pixels_required(pixels);height,width=pixels.shape[:2]
            masks=geometry(width,height,[] if exclusions is None else exclusions)
            rw,rh=resize_shape(width,height)
            canvas=np.full((640,640,3),114,dtype=np.uint8)
            canvas[:rh,:rw]=cv2.resize(cv2.cvtColor(pixels,cv2.COLOR_BGR2RGB),(rw,rh))
            self.net.setInput(cv2.dnn.blobFromImage(canvas))
            outputs=self.net.forward(self.net.getUnconnectedOutLayersNames())
            require(type(outputs) in (list,tuple) and len(outputs)==1)
            return decode_yolox_regions(outputs[0],width=width,height=height,exclusions=[list(b) for b in masks])
        except SourceError:raise
        except Exception:raise SourceError('LOCAL_YOLOX_BOAT_INFERENCE_FAILED') from None
