import numpy as np
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import os
from glob import glob
import cv2

def glob_imgs(path):
    imgs = []
    for ext in ['*.png', '*.jpg', '*.JPEG', '*.JPG']:
        imgs.extend(glob(os.path.join(path, ext)))
    return imgs

def read_camera(intri_name, extri_name, cam_names=[]):
    assert os.path.exists(intri_name), intri_name
    assert os.path.exists(extri_name), extri_name

    intri = FileStorage(intri_name)
    extri = FileStorage(extri_name)
    cams, P = {}, {}
    cam_names = intri.read('names', dt='list')
    for cam in cam_names:
        cams[cam] = {}
        cams[cam]['K'] = intri.read('K_{}'.format( cam))
        cams[cam]['invK'] = np.linalg.inv(cams[cam]['K'])
        Rvec = extri.read('R_{}'.format(cam))
        Tvec = extri.read('T_{}'.format(cam))
        assert Rvec is not None, cam
        R = cv2.Rodrigues(Rvec)[0]
        RT = np.hstack((R, Tvec))

        cams[cam]['RT'] = RT
        cams[cam]['R'] = R
        cams[cam]['Rvec'] = Rvec
        cams[cam]['T'] = Tvec
        cams[cam]['center'] = - Rvec.T @ Tvec
        P[cam] = cams[cam]['K'] @ cams[cam]['RT']
        cams[cam]['P'] = P[cam]

        cams[cam]['dist'] = intri.read('dist_{}'.format(cam))
    cams['basenames'] = cam_names
    return cams

class FileStorage(object):
    def __init__(self, filename, isWrite=False):
        version = cv2.__version__
        self.major_version = int(version.split('.')[0])
        self.second_version = int(version.split('.')[1])

        if isWrite:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            self.fs = open(filename, 'w')
            self.fs.write('%YAML:1.0\r\n')
            self.fs.write('---\r\n')
        else:
            assert os.path.exists(filename), filename
            self.fs = cv2.FileStorage(filename, cv2.FILE_STORAGE_READ)
        self.isWrite = isWrite

    def __del__(self):
        if self.isWrite:
            self.fs.close()
        else:
            cv2.FileStorage.release(self.fs)

    def _write(self, out):
        self.fs.write(out+'\r\n')

    def write(self, key, value, dt='mat'):
        if dt == 'mat':
            self._write('{}: !!opencv-matrix'.format(key))
            self._write('  rows: {}'.format(value.shape[0]))
            self._write('  cols: {}'.format(value.shape[1]))
            self._write('  dt: d')
            self._write('  data: [{}]'.format(', '.join(['{:.3f}'.format(i) for i in value.reshape(-1)])))
        elif dt == 'list':
            self._write('{}:'.format(key))
            for elem in value:
                self._write('  - "{}"'.format(elem))

    def read(self, key, dt='mat'):
        if dt == 'mat':
            output = self.fs.getNode(key).mat()
        elif dt == 'list':
            results = []
            n = self.fs.getNode(key)
            for i in range(n.size()):
                val = n.at(i).string()
                if val == '':
                    val = str(int(n.at(i).real()))
                if val != 'none':
                    results.append(val)
            output = results
        else:
            raise NotImplementedError
        return output

    def close(self):
        self.__del__(self)

def get_Ps(cameras,number_of_cameras):
    Ps = []
    for i in range(0, number_of_cameras):
        P = cameras['world_mat_%d' % i][:3, :].astype(np.float64)
        Ps.append(P)
    return np.array(Ps)


#Gets the fundamental matrix that transforms points from the image of camera 2, to a line in the image of
#camera 1
def get_fundamental_matrix(P_1,P_2):
    P_2_center=np.linalg.svd(P_2)[-1][-1, :]
    epipole=P_1@P_2_center
    epipole_cross=np.zeros((3,3))
    epipole_cross[0,1]=-epipole[2]
    epipole_cross[1, 0] = epipole[2]

    epipole_cross[0,2]=epipole[1]
    epipole_cross[2, 0] = -epipole[1]

    epipole_cross[1, 2] = -epipole[0]
    epipole_cross[2, 1] = epipole[0]

    F = epipole_cross@P_1 @ np.linalg.pinv(P_2)
    return F



# Given a point (curx,cury) in image 0, get the  maximum and minimum
# possible depth of the point, considering the second image silhouette (index j)
def get_min_max_d(curx, cury, P_j, silhouette_j, P_0, Fj0, j):
    # transfer point to line using the fundamental matrix:
    cur_l_1=Fj0 @ np.array([curx,cury,1.0]).astype(np.float)
    cur_l_1 = cur_l_1 / np.linalg.norm(cur_l_1[:2])

    # Distances of the silhouette points from the epipolar line:
    dists = np.abs(silhouette_j.T @ cur_l_1)
    relevant_matching_points_1 = silhouette_j[:, dists < 0.7]

    if relevant_matching_points_1.shape[1]==0:
        return (0.0,0.0)
    X = cv2.triangulatePoints(P_0, P_j, np.tile(np.array([curx, cury]).astype(np.float),
                                                (relevant_matching_points_1.shape[1], 1)).T,
                              relevant_matching_points_1[:2, :])
    depths = P_0[2] @ (X / X[3])
    reldepth=depths >= 0
    depths=depths[reldepth]
    if depths.shape[0] == 0:
        return (0.0, 0.0)

    min_depth=depths.min()
    max_depth = depths.max()

    return min_depth,max_depth

#get all fundamental matrices that trasform points from camera 0 to lines in Ps
def get_fundamental_matrices(P_0, Ps):
    Fs=[]
    for i in range(0,Ps.shape[0]):
        F_i0 = get_fundamental_matrix(Ps[i],P_0)
        Fs.append(F_i0)
    return np.array(Fs)

def get_all_mask_points(masks_dir):
    mask_paths = sorted(glob_imgs(masks_dir))
    mask_points_all=[]
    mask_ims = []
    for path in mask_paths:
        img = mpimg.imread(path)
        cur_mask = img.max(axis=2) > 0.5
        mask_points = np.where(img.max(axis=2) > 0.5)
        xs = mask_points[1]
        ys = mask_points[0]
        mask_points_all.append(np.stack((xs,ys,np.ones_like(xs))).astype(np.float))
        mask_ims.append(cur_mask)
    return mask_points_all,np.array(mask_ims)

def refine_visual_hull(masks, Ps, scale, center):
    num_cam=masks.shape[0]
    GRID_SIZE=100
    MINIMAL_VIEWS=45 # Fitted for DTU, might need to change for different data.
    im_height=masks.shape[1]
    im_width = masks.shape[2]
    xx, yy, zz = np.meshgrid(np.linspace(-scale, scale, GRID_SIZE), np.linspace(-scale, scale, GRID_SIZE),
                             np.linspace(-scale, scale, GRID_SIZE))
    points = np.stack((xx.flatten(), yy.flatten(), zz.flatten()))
    points = points + center[:, np.newaxis]
    appears = np.zeros((GRID_SIZE*GRID_SIZE*GRID_SIZE, 1))
    for i in range(num_cam):
        proji = Ps[i] @ np.concatenate((points, np.ones((1, GRID_SIZE*GRID_SIZE*GRID_SIZE))), axis=0)
        depths = proji[2]
        proj_pixels = np.round(proji[:2] / depths).astype(np.long)
        relevant_inds = np.logical_and(proj_pixels[0] >= 0, proj_pixels[1] < im_height)
        relevant_inds = np.logical_and(relevant_inds, proj_pixels[0] < im_width)
        relevant_inds = np.logical_and(relevant_inds, proj_pixels[1] >= 0)
        relevant_inds = np.logical_and(relevant_inds, depths > 0)
        relevant_inds = np.where(relevant_inds)[0]

        cur_mask = masks[i] > 0.5
        relmask = cur_mask[proj_pixels[1, relevant_inds], proj_pixels[0, relevant_inds]]
        relevant_inds = relevant_inds[relmask]
        appears[relevant_inds] = appears[relevant_inds] + 1

    final_points = points[:, (appears >= MINIMAL_VIEWS).flatten()]
    centroid=final_points.mean(axis=1)
    normalize = final_points - centroid[:, np.newaxis]

    return centroid,np.sqrt((normalize ** 2).sum(axis=0)).mean() * 3,final_points.T

# the normaliztion script needs a set of 2D object masks and camera projection matrices (P_i=K_i[R_i |t_i] where [R_i |t_i] is world to camera transformation)
def get_normalization_function(Ps,mask_points_all,number_of_normalization_points,number_of_cameras,masks_all):
    P_0 = Ps[0]
    Fs = get_fundamental_matrices(P_0, Ps)
    P_0_center = np.linalg.svd(P_0)[-1][-1, :]
    P_0_center = P_0_center / P_0_center[3]

    # Use image 0 as a references
    xs = mask_points_all[0][0, :]
    ys = mask_points_all[0][1, :]

    counter = 0
    all_Xs = []

    # sample a subset of 2D points from camera 0
    indss = np.random.permutation(xs.shape[0])[:number_of_normalization_points]

    for i in indss:
        curx = xs[i]
        cury = ys[i]
        # for each point, check its min/max depth in all other cameras.
        # If there is an intersection of relevant depth keep the point
        observerved_in_all = True
        max_d_all = 1e10
        min_d_all = 1e-10
        for j in range(1, number_of_cameras, 5):
            min_d, max_d = get_min_max_d(curx, cury, Ps[j], mask_points_all[j], P_0, Fs[j], j)

            if abs(min_d) < 0.00001:
                observerved_in_all = False
                break
            max_d_all = np.min(np.array([max_d_all, max_d]))
            min_d_all = np.max(np.array([min_d_all, min_d]))
            if max_d_all < min_d_all + 1e-2:
                observerved_in_all = False
                break
        if observerved_in_all:
            direction = np.linalg.inv(P_0[:3, :3]) @ np.array([curx, cury, 1.0])
            all_Xs.append(P_0_center[:3] + direction * min_d_all)
            all_Xs.append(P_0_center[:3] + direction * max_d_all)
            counter = counter + 1

    print("Number of points:%d" % counter)
    centroid = np.array(all_Xs).mean(axis=0)
    # mean_norm=np.linalg.norm(np.array(allXs)-centroid,axis=1).mean()
    scale = np.array(all_Xs).std()

    # OPTIONAL: refine the visual hull
    centroid,scale,all_Xs = refine_visual_hull(masks_all, Ps, scale, centroid)

    normalization = np.eye(4).astype(np.float32)

    normalization[0, 3] = centroid[0]
    normalization[1, 3] = centroid[1]
    normalization[2, 3] = centroid[2]

    normalization[0, 0] = scale
    normalization[1, 1] = scale
    normalization[2, 2] = scale
    return normalization,all_Xs


def get_normalization(source_dir, cameras):
    print('Preprocessing', source_dir)


    number_of_normalization_points = 100

    masks_dir='{0}/mask'.format(source_dir)
    # cameras=np.load('{0}/{1}.npz'.format(source_dir, cameras_filename))

    mask_points_all,masks_all=get_all_mask_points(masks_dir)
    number_of_cameras = len(masks_all)
    Ps = get_Ps(cameras, number_of_cameras)

    normalization,all_Xs=get_normalization_function(Ps, mask_points_all, number_of_normalization_points, number_of_cameras,masks_all)

    cameras_new={}
    for i in range(number_of_cameras):
        cameras_new['scale_mat_%d'%i]=normalization
        cameras_new['world_mat_%d' % i] = np.concatenate((Ps[i],np.array([[0,0,0,1.0]])),axis=0).astype(np.float32)

    np.savez('{0}/{1}_new.npz'.format(source_dir, "cameras_after_normalize"), **cameras_new)

    print(normalization)
    print('--------------------------------------------------------')

    if False: #for debugging
        for i in range(number_of_cameras):
            plt.figure()

            plt.imshow(mpimg.imread('%s/%03d.png' % (masks_path, i)))
            xy = (Ps[i,:2, :] @ (np.concatenate((np.array(all_Xs), np.ones((len(all_Xs), 1))), axis=1).T)) / (
                        Ps[i,2, :] @ (np.concatenate((np.array(all_Xs), np.ones((len(all_Xs), 1))), axis=1).T))

            plt.plot(xy[0, :], xy[1, :], '*')
            plt.show()

if __name__ == '__main__':
    cam_path = 'your_path'
    views = ['Camera_B1', 'Camera_B2', 'Camera_B3', 'Camera_B4', 'Camera_B5',
             'Camera_B6', 'Camera_B7', 'Camera_B8', 'Camera_B9', 'Camera_B10',
             'Camera_B11', 'Camera_B12', 'Camera_B13', 'Camera_B14', 'Camera_B15',
             'Camera_B16', 'Camera_B17', 'Camera_B18', 'Camera_B19', 'Camera_B20',
             'Camera_B21', 'Camera_B22', 'Camera_B23']
    cameras = read_camera(join(cam_path, 'intri.yml'), join(cam_path, 'extri.yml'), views)
    cameras = {key: cameras[key] for key in views}

    cam_dict = {}
    scale_mat = np.diag([1.0, 1.0, 1.0, 1.0]).astype(np.float32)
    i = 0
    for view in views:
        cam = cameras[view]
        intrinsic = np.diag([1.0, 1.0, 1.0, 1.0]).astype(np.float32)
        intrinsic[:3, :3] = cam['K']
        pose = np.diag([1.0, 1.0, 1.0, 1.0])
        pose[:3, :] = cam['RT']
        # pose[:3, :3] = cam['R']
        # pose[:3, 3] = cam['T']

        world_mat = intrinsic @ pose
        world_mat = world_mat.astype(np.float32)

        cam_dict['world_mat_{}'.format(i)] = world_mat
        cam_dict['scale_mat_{}'.format(i)] = scale_mat
        i += 1

    np.savez(os.path.join(cam_path, 'cameras_before_normalize.npz'), **cam_dict)

    get_normalization(cam_path, cam_dict)

    print()