"""Bounded ranking of actual recorded pixels. No identity verdict is produced."""
import math

import cv2
import numpy as np


def capture_focus(frame):
    """Prefer legible edges; darkness, clipping and sensor grain are not detail."""
    try:
        height,width=frame.shape[:2]
        if min(height,width)<16:
            return 0.0
        scale=min(1,320/max(height,width))
        small=cv2.resize(frame,(max(1,round(width*scale)),max(1,round(height*scale)))) if scale<1 else frame
        gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY) if small.ndim==3 else small
        light=float(gray.mean())
        clipped=float(np.mean((gray<8)|(gray>247)))
        if not 18<light<242 or clipped>.55:
            return 0.0
        clean=cv2.GaussianBlur(gray,(3,3),.8)
        raw=float(cv2.Laplacian(gray,cv2.CV_64F).var())
        lap=cv2.Laplacian(clean,cv2.CV_64F)
        smooth=float(lap.var())
        residual=float(np.mean(np.abs(gray.astype(np.float32)-clean)))
        if residual>6 and raw>30*max(1,smooth):
            return 0.0
        tiles=[float(np.mean(part*part)) for part in
               (lap[y:y+max(1,gray.shape[0]//4),x:x+max(1,gray.shape[1]//4)]
                for y in range(0,gray.shape[0],max(1,gray.shape[0]//4))
                for x in range(0,gray.shape[1],max(1,gray.shape[1]//4))) if part.size]
        detail=float(np.percentile(tiles,90)) if tiles else 0
        return (1-clipped)*(math.log1p(smooth)+.25*math.log1p(detail))
    except (cv2.error,ValueError,TypeError,AttributeError):
        return 0.0


class SharpWindowSampler:
    """Inspect at most 8 candidates/sec; retain one real frame per half second."""
    def __init__(self):
        self.next_sample=0.0
        self.pending=None
        self.candidates=[]
        self.examined=0

    def _flush(self):
        if self.pending is None:
            return
        _,seconds,frame,_=self.pending
        ok,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,88])
        if not ok:
            raise ValueError('A camera frame could not be encoded')
        self.candidates.append((seconds,jpeg.tobytes()))
        self.pending=None

    def consider(self,frame,seconds):
        if not math.isfinite(seconds) or seconds<0:
            raise ValueError('Invalid camera frame time')
        if seconds+1e-6<self.next_sample:
            return
        self.next_sample=(math.floor(seconds*8+1e-6)+1)/8
        self.examined+=1
        bucket=math.floor(seconds*2+1e-6)
        if self.pending is not None and self.pending[0]!=bucket:
            self._flush()
        score=capture_focus(frame)
        if self.pending is None or score>self.pending[3]:
            height,width=frame.shape[:2]
            scale=min(1,1100/max(height,width))
            actual=cv2.resize(frame,(max(1,int(width*scale)),max(1,int(height*scale)))) if scale<1 else frame
            self.pending=(bucket,seconds,actual.copy(),score)

    def finish(self):
        self._flush()
        return self.candidates


def correspondence(reference,frame):
    """Mutual, coherent matches rank views only; repeated marks cannot certify identity."""
    points,descriptors,_=reference
    other_points,other_descriptors,quality=frame
    empty={'score':0.0,'detail_score':0.0,'inliers':0,'coverage':0.0}
    if descriptors is None or other_descriptors is None or min(len(descriptors),len(other_descriptors))<8 or quality<=0:
        return empty
    try:
        matcher=cv2.BFMatcher(cv2.NORM_HAMMING)
        reverse={pair[0].queryIdx:pair[0].trainIdx for pair in matcher.knnMatch(other_descriptors,descriptors,k=2)
                 if len(pair)==2 and pair[0].distance<.75*pair[1].distance}
        good=[pair[0] for pair in matcher.knnMatch(descriptors,other_descriptors,k=2)
              if len(pair)==2 and pair[0].distance<.75*pair[1].distance
              and reverse.get(pair[0].trainIdx)==pair[0].queryIdx]
        if len(good)<6:
            return empty
        source=np.float32([points[m.queryIdx].pt for m in good])
        target=np.float32([other_points[m.trainIdx].pt for m in good])
        transform,mask=cv2.findHomography(source,target,cv2.RANSAC,4,maxIters=500)
        if transform is None or mask is None or not np.isfinite(transform).all():
            return empty
        selected=mask.ravel().astype(bool)
        inliers=int(selected.sum())
        if inliers<6 or inliers<len(good)*.35:
            return empty
        all_points=np.float32([point.pt for point in points])
        whole=max(1,float(cv2.contourArea(cv2.convexHull(all_points))))
        covered=float(cv2.contourArea(cv2.convexHull(source[selected])))
        coverage=min(1,max(0,covered/whole))
        if coverage<.005:
            return empty
        # Enlargement may make a number legible even when less of the item is
        # visible. This creates a second ranking hint, not OCR or a new claim.
        src_span=np.ptp(source[selected],axis=0)
        dst_span=np.ptp(target[selected],axis=0)
        enlargement=float(np.median(dst_span/np.maximum(src_span,1)))
        score=inliers*(.4+.6*quality)*(.7+.3*math.sqrt(coverage))
        detail=inliers*quality*min(2,max(.5,enlargement))
        return {'score':score,'detail_score':detail,'inliers':inliers,'coverage':coverage}
    except (cv2.error,ValueError,TypeError,AttributeError):
        return empty


def choose_frames(rankings,frames,limit):
    """Reference coverage, timeline anchors, separated views, then detail top-ups."""
    count=len(frames)
    chosen=set()
    thumbnails={}
    def duplicate(a,b):
        if frames[a]['content']==frames[b]['content']:
            return True
        for index in (a,b):
            if index not in thumbnails:
                picture=cv2.imdecode(np.frombuffer(frames[index]['content'],np.uint8),cv2.IMREAD_GRAYSCALE)
                if picture is None:
                    thumbnails[index]=None
                else:
                    small=cv2.resize(picture,(32,24)).astype(np.float32)
                    thumbnails[index]=(small-small.mean())/max(8,float(small.std()))
        return thumbnails[a] is not None and thumbnails[b] is not None and float(np.mean(np.abs(thumbnails[a]-thumbnails[b])))<.12
    ranked=[sorted(entries,key=lambda item:(item['score'],item['inliers'],item['index']),reverse=True) for entries in rankings]
    # Never let one easy-to-match reference exhaust the shared evidence budget.
    for entries in ranked:
        best=next((item for item in entries if item['score']>0),None)
        if best and len(chosen)<limit:
            chosen.add(best['index'])
    for index in dict.fromkeys((0,count//2,count-1)):
        if len(chosen)<limit:
            chosen.add(index)
    def time(index):
        value=frames[index].get('seconds') if hasattr(frames[index],'get') else frames[index]['seconds']
        return float(value) if isinstance(value,(int,float)) and math.isfinite(value) else index*.5
    for entries in ranked:
        positives=[item for item in entries if item['score']>0]
        if not positives:
            continue
        best=positives[0]['index']
        separated=next((item for item in positives if item['index'] not in chosen
                        and abs(time(item['index'])-time(best))>=.75 and not duplicate(best,item['index'])),None)
        if separated and len(chosen)<limit:
            chosen.add(separated['index'])
    for entries in ranked:
        details=sorted(entries,key=lambda item:(item['detail_score'],item['score'],item['index']),reverse=True)
        best=next((item for item in details if item['score']>0 and item['index'] not in chosen
                   and not any(duplicate(item['index'],index) for index in chosen)),None)
        if best and len(chosen)<limit:
            chosen.add(best['index'])
    for index in ([round(i*(count-1)/(limit-1)) for i in range(limit)] if limit>1 else [0]):
        if len(chosen)<limit:
            chosen.add(index)
    return sorted(chosen),ranked
