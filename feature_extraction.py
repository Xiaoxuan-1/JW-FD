# -*- coding: utf-8 -*-
"""
特征提取模块 - 从太阳磁图中提取物理特征
"""

import numpy as np
from scipy.signal import convolve2d
from scipy.stats import skew, kurtosis
from scipy import ndimage
import pywt
from skimage import measure

def fluxValues(magnetogram):
    """计算磁通量特征"""
    posSum = np.sum(magnetogram[magnetogram > 0])
    negSum = np.sum(magnetogram[magnetogram < 0])
    signSum = posSum + negSum
    unsignSum = posSum - negSum
    return posSum, negSum, signSum, unsignSum

def gradient(image):
    """使用Sobel算子计算梯度"""
    sobelx = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
    sobely = [[1, 2, 1], [0, 0, 0], [-1, -2, -1]]
    
    gx = convolve2d(image, sobelx, mode='same')
    gy = convolve2d(image, sobely, mode='same')
    
    M = (gx ** 2 + gy ** 2) ** (1. / 2)
    return M

def Gradfeat(image):
    """计算梯度统计特征"""
    res = gradient(image).flatten()
    men = np.mean(res)
    strd = np.std(res)
    med = np.median(res)
    minim = np.amin(res)
    maxim = np.amax(res)
    skw = skew(res)
    kurt = kurtosis(res)
    return men, strd, med, minim, maxim, skw, kurt

def wavel(image):
    """计算小波能量特征"""
    # 计算小波能量
    LL, L5, L4, L3, L2, L1 = pywt.wavedec2(image, 'haar', level=5)
    L1e = np.sum(np.absolute(L1))
    L2e = np.sum(np.absolute(L2))
    L3e = np.sum(np.absolute(L3))
    L4e = np.sum(np.absolute(L4))
    L5e = np.sum(np.absolute(L5))
    return L1e, L2e, L3e, L4e, L5e

def extractNL(image):
    """提取中性线轮廓"""
    avg10 = (1. / 100) * np.ones([10, 10])
    avgim = convolve2d(image, avg10, mode='same')
    out = measure.find_contours(avgim, level=0)
    return out

def NLmaskgen(contours, image):
    """生成中性线掩码"""
    mask = np.zeros((image.shape))
    for n, contour in enumerate(contours):
        for i in range(len(contour)):
            y = int(round(contour[i, 1]))
            x = int(round(contour[i, 0]))
            mask[x, y] = 1.
    return mask

def findTGWNL(image):
    """寻找梯度加权中性线"""
    m = 0.2 * np.amax(np.absolute(image))
    width = image.shape[0]
    height = image.shape[1]
    out = np.zeros([height, width])
    out[abs(image) >= m] = 1
    return out

def curvature(contour):
    """计算轮廓曲率"""
    angles = np.zeros([contour.shape[0]])
    yvals = np.around(contour[:, 1])
    xvals = np.around(contour[:, 0])
    for i in range(contour.shape[0]):
        if i < contour.shape[0] - 1:
            n = i + 1
        else:
            n = 0
        y = int(yvals[i])
        x = int(xvals[i])
        yn = int(yvals[n])
        xn = int(xvals[n])
        num = yn - y
        den = xn - x
        if den != 0:
            angles[i] = np.arctan(num / den)
        elif num < 0:
            angles[i] = 3 * np.pi / 2
        else:
            angles[i] = np.pi / 2
    return angles

def bendergy(angles):
    """计算弯曲能量"""
    fact = 1. / len(angles)
    count = 0.
    for i in range(len(angles)):
        if i < len(angles) - 1:
            n = i + 1
        else:
            n = 0
        T = angles[i]
        Tn = angles[n]
        count += (T - Tn) ** 2
    
    BE = count * fact
    return BE

def NLfeat(image):
    """计算中性线特征"""
    grad = gradient(image)
    contours = extractNL(image)
    ma = NLmaskgen(contours, image)
    gwnl = np.zeros([grad.shape[0], grad.shape[1]])
    gwnl = grad * ma
    thresh = findTGWNL(gwnl)
    NLlen = np.sum(thresh)
    
    struct = [[1, 1, 1], [1, 1, 1], [1, 1, 1]]
    lines, numlines = ndimage.label(thresh, struct)
    
    GWNLlen = np.sum(ma)
    Flag = True
    if not contours:
        return 0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0.
    else:
        for n, contour in enumerate(contours):
            curve = curvature(contour)
            if Flag:
                angstore = np.zeros([len(curve)])
                angstore = curve
                BEstore = np.zeros([len(contours)])
                Flag = False
            else:
                angstore = np.concatenate((curve, angstore))
            BEstore[n] = bendergy(curve)
    
    return float(NLlen), float(numlines), float(GWNLlen), float(np.mean(angstore)), np.std(angstore), np.median(
        angstore), np.amin(angstore), np.amax(angstore), np.mean(BEstore), np.std(BEstore), np.median(BEstore), np.amin(
        BEstore), np.amax(BEstore)

def extract_all_features(image):
    """提取所有29个特征"""
    # 图像预处理：减去128作为零磁通量偏移
    image = image - 128
    
    # 提取各类特征
    G = Gradfeat(image)      # 7个梯度特征
    NL = NLfeat(image)       # 13个中性线特征
    wav = wavel(image)       # 5个小波特征
    F = fluxValues(image)    # 4个磁通量特征
    
    # 合并所有特征
    features = np.concatenate((G, NL, wav, F))
    return features