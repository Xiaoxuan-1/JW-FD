# -*- coding: utf-8 -*-
"""
特征提取模块 - 从太阳磁图中提取 29 维物理特征（性能优化版）

与早期实现的关系
================
本文件同时放在仓库和 JW-FD-fixed/code，是早期特征脚本的性能重写。
**29 个特征的顺序与含义不变**。
梯度 / 通量 / 小波在本项目输入域上与参考实现逐位相同；
**中性线（NL）类特征刻意不再逐位复现参考实现**，见下面「10x10 均值」。

已做的优化
----------
1. ``gradient``  : Sobel 3x3 -> 可分离 1-D correlate1d，约 4x；导入时自检，
                   失败则回退 ``convolve2d``。
2. ``extractNL`` : 10x10 均值改为 ``ndimage.uniform_filter``（先求和再除），
                   约 30x。这是一次**有意的数值修正**，不是逐位复现。
3. 梯度只算一次   : ``_extract`` 统一计算后传给 ``Gradfeat`` / ``NLfeat``。
4. ``NLmaskgen``  : 花式索引。
5. ``curvature`` / ``bendergy`` : 向量化。
6. ``Gradfeat``   : 共享中心矩，复刻 scipy.stats 的 skew/kurtosis。

10x10 均值：为什么改、改成什么
------------------------------
参考实现 ``convolve2d(image, (1/100)*ones, mode='same')`` 是先乘 0.01 再加。
PNG 整数域上约 8% 像素的 10x10 窗口和**恰好为 0**（宁静区），纸上的均值必须是 0，
但 0.01 无法在二进制里精确表示，累加残渣 ~1e-15 的正负号被
``find_contours(level=0)`` 当成中性线。这不是 Boucheron 算法错了，
是「除以 100」的浮点写法在精确零点上失真。

本版改为 ``uniform_filter(..., size=10, mode='constant', cval=0)``：
先做窗口和再除一次，精确零点仍为 0.0，轮廓由磁场决定而不是舍入残渣。
NL 列因此会与已发布 CSV 不同；本数据集反正因 hmi_norm / −128 / NaN 已全量重算，
一并修正。

FITS 取向
---------
step2b 先把裁剪结果 rot180，写入 fits_600。step4 **不再翻转**，
FITS 版特征与 rot180 后的像素一一对应。step3 只做 ``np.flipud``，
并且只作用于 PNG。

本文件同时修复的一个语义 bug（与性能无关）
------------------------------------------
参考实现的 ``extract_all_features`` 无条件做 ``image = image - 128``，
被 FITS 与 PNG 两条通路共用。上游 DRYAD 参考代码中这个偏移只用于 PNG
（``# Offset for zero flux``），FITS 高斯域的零点天然为 0，不应平移。
因此这里拆成 ``extract_all_features_png`` / ``extract_all_features_fits``；
PNG 零点取 127 而非 128，因为 ``astype('uint8')`` 截断下 0 G 落在灰阶 127
这个 bin（覆盖 B ∈ [-Th/255, +Th/255)，恰好以零为中心）。
"""

import numpy as np
from scipy.signal import convolve2d
from scipy.stats import skew, kurtosis          # noqa: F401  (保留导出，便于对照)
from scipy import ndimage
import pywt
from skimage import measure

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: uint8 截断下 0 G 对应的灰阶零点
ZERO_LEVEL_PNG = 127.0

# Sobel 核（与参考实现一致；convolve2d 会翻转核，可分离形式用 correlate1d 不翻转）
_SOBEL_X = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
_SOBEL_Y = [[1, 2, 1], [0, 0, 0], [-1, -2, -1]]
# 翻转后 sobelx 的相关核 = outer([1,2,1], [1,0,-1])
_DIFF3 = np.array([1.0, 0.0, -1.0])
_SMOOTH3 = np.array([1.0, 2.0, 1.0])

_LABEL_STRUCT = [[1, 1, 1], [1, 1, 1], [1, 1, 1]]

# 自检结果，见 _selftest()
_GRAD_SEP_EXACT = True


# ---------------------------------------------------------------------------
# 磁通量特征（未改动）
# ---------------------------------------------------------------------------

def fluxValues(magnetogram):
    """计算磁通量特征"""
    posSum = np.sum(magnetogram[magnetogram > 0])
    negSum = np.sum(magnetogram[magnetogram < 0])
    signSum = posSum + negSum
    unsignSum = posSum - negSum
    return posSum, negSum, signSum, unsignSum


# ---------------------------------------------------------------------------
# 梯度
# ---------------------------------------------------------------------------

def _gradient_convolve2d(image):
    """参考实现的原始写法，作为自检基准与回退路径。"""
    gx = convolve2d(image, _SOBEL_X, mode='same')
    gy = convolve2d(image, _SOBEL_Y, mode='same')
    return (gx ** 2 + gy ** 2) ** (1. / 2)


def _gradient_separable(image):
    """可分离 1-D 形式。gy 与参考实现符号相反，平方后无影响。"""
    gx = ndimage.correlate1d(image, _DIFF3, axis=1, mode='constant', cval=0.0)
    gx = ndimage.correlate1d(gx, _SMOOTH3, axis=0, mode='constant', cval=0.0)
    gy = ndimage.correlate1d(image, _DIFF3, axis=0, mode='constant', cval=0.0)
    gy = ndimage.correlate1d(gy, _SMOOTH3, axis=1, mode='constant', cval=0.0)
    return (gx ** 2 + gy ** 2) ** (1. / 2)


def gradient(image):
    """使用Sobel算子计算梯度幅值"""
    if _GRAD_SEP_EXACT:
        return _gradient_separable(image)
    return _gradient_convolve2d(image)


# ---------------------------------------------------------------------------
# 梯度统计特征
# ---------------------------------------------------------------------------

def _moments_stats(res):
    """一次性算出 mean/std/skew/kurtosis，与 numpy / scipy.stats 逐位一致。

    复刻 scipy 1.9.1 ``_stats_py._moment`` 的表达式树：
        mean = a.mean(axis, keepdims=True)
        m_k  = np.mean((a-mean)**2 [* (a-mean) | **2], axis)
    并复用 ``np.std(a) == sqrt(m2)``（numpy ``_var`` 与 ``_moment`` 的运算完全同构）。
    """
    mean_k = res.mean(0, keepdims=True)
    azm = res - mean_k
    azm2 = azm ** 2
    m2 = np.mean(azm2, 0)
    # m3 = mean((a-mean)^2 * (a-mean))，原地写回 azm 省一次分配
    np.multiply(azm2, azm, out=azm)
    m3 = np.mean(azm, 0)
    # m4 = mean(((a-mean)^2)^2)
    np.multiply(azm2, azm2, out=azm2)
    m4 = np.mean(azm2, 0)

    with np.errstate(all='ignore'):
        zero = (m2 <= (np.finfo(m2.dtype).resolution * mean_k[0]) ** 2)
        skw = np.where(zero, np.nan, m3 / m2 ** 1.5)
        kur = np.where(zero, np.nan, m4 / m2 ** 2.0)
    return mean_k[0], np.sqrt(m2), skw.item(), kur.item() - 3


def Gradfeat(image, grad=None):
    """计算梯度统计特征

    Parameters
    ----------
    image : ndarray
        已完成零点平移的磁图。
    grad : ndarray, optional
        预先算好的 ``gradient(image)``；给出时不再重复计算。
    """
    if grad is None:
        grad = gradient(image)
    # 参考实现用 flatten()（复制）；grad 是 C 连续的，reshape(-1) 是视图，
    # 长度与连续性相同 => np.mean/std/median 的求和顺序完全一致。
    res = grad.reshape(-1)
    men, strd, skw, kurt = _moments_stats(res)
    med = np.median(res)
    minim = np.amin(res)
    maxim = np.amax(res)
    return men, strd, med, minim, maxim, skw, kurt


# ---------------------------------------------------------------------------
# 小波能量特征（未改动）
# ---------------------------------------------------------------------------

def wavel(image):
    """计算小波能量特征"""
    LL, L5, L4, L3, L2, L1 = pywt.wavedec2(image, 'haar', level=5)
    L1e = np.sum(np.absolute(L1))
    L2e = np.sum(np.absolute(L2))
    L3e = np.sum(np.absolute(L3))
    L4e = np.sum(np.absolute(L4))
    L5e = np.sum(np.absolute(L5))
    return L1e, L2e, L3e, L4e, L5e


# ---------------------------------------------------------------------------
# 10x10 均值滤波：先求和再除（修正参考实现的 0.01 核舍入）
# ---------------------------------------------------------------------------

def _mean10(image):
    """10x10 盒式均值，与 ``convolve2d(ones)/100`` 同相位。

    不用 ``(1/100)*ones`` 核：那个写法会在窗口和恰好为 0 的像素上留下
    ±1e-15 残渣，被 ``find_contours(level=0)`` 当成假中性线。
    ``uniform_filter`` 的滑动和也会留下 ~1e-14 残渣，这里把 |avg|<1e-12
    的值钉成 0（远小于 1 灰阶/100 = 0.01，不会碰到真实信号）。
    """
    avg = ndimage.uniform_filter(
        np.asarray(image, dtype=np.float64),
        size=10,
        mode='constant',
        cval=0.0,
    )
    avg[np.abs(avg) < 1e-12] = 0.0
    return avg


def extractNL(image):
    """提取中性线轮廓"""
    avgim = _mean10(image)
    return measure.find_contours(avgim, level=0)


# ---------------------------------------------------------------------------
# 中性线掩码
# ---------------------------------------------------------------------------

def NLmaskgen(contours, image):
    """生成中性线掩码

    参考实现逐点 ``mask[int(round(c[i,0])), int(round(c[i,1]))] = 1.``；
    Python ``round()`` 作用在 ``np.float64`` 上与 ``np.round`` 同为
    round-half-to-even，且重复赋值幂等，因此花式索引完全等价。
    """
    mask = np.zeros((image.shape))
    if not len(contours):
        return mask
    pts = np.concatenate(contours, axis=0)
    if pts.shape[0] == 0:
        return mask
    xi = np.round(pts[:, 0]).astype(np.intp)
    yi = np.round(pts[:, 1]).astype(np.intp)
    mask[xi, yi] = 1.
    return mask


def findTGWNL(image):
    """寻找梯度加权中性线"""
    absim = np.absolute(image)
    m = 0.2 * np.amax(absim)
    width = image.shape[0]
    height = image.shape[1]
    out = np.zeros([height, width])
    out[absim >= m] = 1
    return out


# ---------------------------------------------------------------------------
# 曲率 / 弯曲能量
# ---------------------------------------------------------------------------

def _angles_from_int_coords(x, y, nxt):
    """按参考实现的分支规则算 arctan 角度（整数差分 + 除零特例）。"""
    num = y[nxt] - y
    den = x[nxt] - x
    angles = np.zeros(x.shape[0])
    nz = den != 0
    # num/den 在参考实现里是 Python int 的真除法，等价于 int64 数组的 true_divide
    angles[nz] = np.arctan(num[nz] / den[nz])
    zr = ~nz
    if zr.any():
        angles[zr] = np.where(num[zr] < 0, 3 * np.pi / 2, np.pi / 2)
    return angles


def curvature(contour):
    """计算轮廓曲率（向量化，与参考实现逐位相同）"""
    p = contour.shape[0]
    if p == 0:
        return np.zeros([0])
    yvals = np.around(contour[:, 1])
    xvals = np.around(contour[:, 0])
    # int() 截断作用在已取整的浮点上 => 与 astype(int64) 等价
    y = yvals.astype(np.int64)
    x = xvals.astype(np.int64)
    nxt = np.arange(1, p + 1, dtype=np.intp)
    nxt[p - 1] = 0                       # 最后一个点的 next 环绕回第 0 个点
    return _angles_from_int_coords(x, y, nxt)


def bendergy(angles):
    """计算弯曲能量

    参考实现是 ``count = sum_i (T_i - T_{i+1})**2``（顺序累加，末点环绕），
    再 ``BE = count * (1./len)``。``np.cumsum`` 是严格顺序累加，取最后一项
    与 Python 循环逐位相同；``np.sum`` 用 pairwise 求和则不同，故不能用。
    """
    n = len(angles)
    fact = 1. / n
    dsq = (angles - np.roll(angles, -1)) ** 2
    count = np.cumsum(dsq)[-1]
    return count * fact


def _curv_bend_all(contours):
    """一次性算出所有轮廓的 angstore / BEstore。

    返回值与参考实现的循环完全一致，包括：
      * ``angstore`` 用 ``np.concatenate((curve, angstore))`` 逐次**前插**，
        最终顺序是轮廓的**逆序**（这会影响 np.mean/np.std 的 pairwise 求和结果，
        必须保持）；
      * ``BEstore`` 按轮廓正序，长度 ``len(contours)``。
    """
    ncont = len(contours)
    lens = np.array([len(c) for c in contours], dtype=np.intp)
    if ncont == 0 or not lens.all():
        # 退化情形（find_contours 不会产生空轮廓）：走参考实现的循环，
        # 保持连同异常在内的行为一致。
        flag = True
        angstore = None
        bestore = None
        for i, contour in enumerate(contours):
            curve = curvature(contour)
            if flag:
                angstore = curve
                bestore = np.zeros([ncont])
                flag = False
            else:
                angstore = np.concatenate((curve, angstore))
            bestore[i] = bendergy(curve)
        return angstore, bestore

    ends = np.cumsum(lens)
    starts = ends - lens
    pts = np.concatenate(contours, axis=0)
    p = pts.shape[0]

    y = np.around(pts[:, 1]).astype(np.int64)
    x = np.around(pts[:, 0]).astype(np.int64)
    nxt = np.arange(1, p + 1, dtype=np.intp)
    nxt[ends - 1] = starts               # 每条轮廓末点环绕回该轮廓首点
    angles = _angles_from_int_coords(x, y, nxt)

    dsq = (angles - angles[nxt]) ** 2
    bestore = np.empty(ncont)
    for k in range(ncont):
        s, e = starts[k], ends[k]
        bestore[k] = np.cumsum(dsq[s:e])[-1] * (1. / lens[k])

    angstore = np.concatenate([angles[starts[k]:ends[k]]
                               for k in range(ncont - 1, -1, -1)])
    return angstore, bestore


# ---------------------------------------------------------------------------
# 中性线特征
# ---------------------------------------------------------------------------

def NLfeat(image, grad=None):
    """计算中性线特征

    Parameters
    ----------
    image : ndarray
        已完成零点平移的磁图。
    grad : ndarray, optional
        预先算好的 ``gradient(image)``；给出时不再重复计算。
    """
    if grad is None:
        grad = gradient(image)
    contours = extractNL(image)
    ma = NLmaskgen(contours, image)
    gwnl = grad * ma
    thresh = findTGWNL(gwnl)
    NLlen = np.sum(thresh)

    lines, numlines = ndimage.label(thresh, _LABEL_STRUCT)

    GWNLlen = np.sum(ma)
    if not contours:
        return 0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0.

    angstore, BEstore = _curv_bend_all(contours)
    return (float(NLlen), float(numlines), float(GWNLlen),
            float(np.mean(angstore)), np.std(angstore), np.median(angstore),
            np.amin(angstore), np.amax(angstore),
            np.mean(BEstore), np.std(BEstore), np.median(BEstore),
            np.amin(BEstore), np.amax(BEstore))


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def _extract(image):
    """在已完成零点平移的数组上提取 29 个特征。

    特征顺序与参考实现 ``np.concatenate((G, NL, wav, F))`` 完全一致：
    7 个梯度 + 13 个中性线 + 5 个小波 + 4 个磁通量。
    """
    grad = gradient(image)               # 只算一次，同时供 Gradfeat / NLfeat 使用
    G = Gradfeat(image, grad=grad)       # 7 个梯度特征
    NL = NLfeat(image, grad=grad)        # 13 个中性线特征
    wav = wavel(image)                   # 5 个小波特征
    F = fluxValues(image)                # 4 个磁通量特征
    return np.concatenate((G, NL, wav, F))


def extract_all_features_png(image):
    """PNG 强度域：输入 0-255 灰度，减 127 归零"""
    return _extract(np.asarray(image, dtype=float) - ZERO_LEVEL_PNG)


def extract_all_features_fits(magnetogram):
    """FITS 高斯域：输入原始高斯值，零点天然为 0，不做任何平移；NaN 填 0 G"""
    m = np.array(magnetogram, dtype=float)      # 总是复制，不动调用方的数组
    m[np.isnan(m)] = 0.0
    return _extract(m)


extract_all_features = extract_all_features_png   # 兼容旧导入


# ---------------------------------------------------------------------------
# 导入时自检：确认两个"复刻浮点行为"的优化在当前 scipy 下依然逐位成立
# ---------------------------------------------------------------------------

def _selftest(verbose=False):
    """校验可分离 Sobel；并确认整数平衡窗口的均值精确为 0。"""
    global _GRAD_SEP_EXACT
    rng = np.random.RandomState(20260828)

    b = (rng.standard_normal((37, 41)).astype(np.float32) * 900.0).astype(np.float64)
    c = rng.randint(-127, 129, (37, 41)).astype(np.float64)
    _GRAD_SEP_EXACT = (np.array_equal(_gradient_convolve2d(b), _gradient_separable(b))
                       and np.array_equal(_gradient_convolve2d(c),
                                          _gradient_separable(c)))

    # 整数平衡窗口：窗口和为 0 的像素，均值必须是精确 0（旧 0.01 核会留下 ±1e-15）
    tile = np.array([1.0] * 50 + [-1.0] * 50, dtype=np.float64).reshape(10, 10)
    img = np.zeros((24, 24), dtype=np.float64)
    img[7:17, 7:17] = tile
    window_sum = convolve2d(img, np.ones((10, 10), dtype=np.float64), mode='same')
    avg = _mean10(img)
    zero_sum = window_sum == 0
    if np.max(np.abs(avg[zero_sum]), initial=0.0) > 1e-15:
        raise RuntimeError(
            '窗口和为 0 的像素均值不是精确 0: max=%r'
            % (np.max(np.abs(avg[zero_sum])),)
        )
    ref = window_sum / 100.0
    ref[np.abs(ref) < 1e-12] = 0.0
    if np.max(np.abs(avg - ref)) > 1e-12:
        raise RuntimeError('uniform_filter 与 convolve2d(ones)/100 相位不一致')

    old = convolve2d(img, (1. / 100) * np.ones((10, 10)), mode='same')
    if verbose:
        print('separable Sobel    : %s' % _GRAD_SEP_EXACT)
        print('exact-zero pixels  : %d, old-kernel noise max %r'
              % (int(zero_sum.sum()), np.max(np.abs(old[zero_sum]))))
    return _GRAD_SEP_EXACT


_selftest()
