import torch
import mdtraj as md
from mdtraj.formats.netcdf import NetCDFTrajectoryFile
import numpy as np
import random
import os
import MDAnalysis as mda
from tqdm import tqdm
from sklearn.metrics import r2_score, mean_squared_error, silhouette_score
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from matplotlib import pyplot as plt

from .autoencoder import *

# from torch.utils.data import DataLoader

def set_seed(seed:int=42):
    r'''
Set seed for the module
-----------------------
seed (int) : seed
    '''
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        

def pathExists(path:str):
    r'''
Check if the given path exists
------------------------------
path (str) : path to check existance
    '''
    if not os.path.exists(path):
        raise FileNotFoundError(f'{path} does not exist') 


def read_traj(traj_:str, top_:str, memmap:bool=False, stride:int=1, chunk:int=100):
    r"""
Create a Dataloader to train compressor model.
----------------------------------------------
traj_ (str) : Trajectory path -- netcdf format
top_ (str) : Topology file 
memmap (bool) : Create memory map (if RAM is not enough) [Default=False]
stride (int) : Only read every stride-th frame [Default=1]
chunk (int) : Number of frames to load at once from disk per iteration. If 0, load all [Default=1000]
batch_size (int) : samples per batch to load [Default=128]
    """
    if chunk < stride:
        raise ValueError('chunk should be higher than stride')
    try:
        u = mda.Universe(top_, traj_)
        n_atoms = len(u.atoms)
        n_frames = len(u.trajectory)
    except:
        with NetCDFTrajectoryFile(traj_, mode='r', force_overwrite=False) as u:
            n_atoms = u.n_atoms
            n_frames = u.n_frames

    print(f'\nTrajectory stats : #_Frames = {n_frames}\t#_Atoms = {n_atoms}')
    print('_'*70,'\n')
    print(f'Start reading coordinates from trajectory to train model...\n[{int(n_frames/stride)} frames with stride {stride}]')

    if memmap:
        centered_xyz = np.memmap('temp_traj.dat', dtype=np.float32, mode='w+', shape=(int(n_frames/stride), n_atoms, 3))
    else:
        centered_xyz = np.empty(dtype=np.float32, shape=(int(n_frames/stride)+1, n_atoms, 3))
      
    start_frame = 0
    for n, chunk in tqdm(enumerate(md.iterload(traj_, top=top_, chunk=chunk, stride=stride)), total=int(n_frames/(chunk*stride)), bar_format='Loading trajectory: {percentage:6.2f}% |{bar}|', ncols=50):

        # Remove rotation: algn on 1st frame of the trajectory or a given reference pdb frame
        if n == 0:
            init_frame = chunk[0]
    
        md.Trajectory.superpose(chunk, init_frame)

        # Remove translation: Center the COM of each frame
        for i in range(chunk.n_frames):
            frame_positions = chunk.xyz[i, :, :]
            com = np.mean(frame_positions, axis=0)
            centered_xyz[start_frame + i, :, :] = frame_positions - com
    
        start_frame += chunk.n_frames
    if memmap:
        centered_xyz.flush()

    return centered_xyz.reshape(-1,1,n_atoms,3)
    

def fitMetrics(model, dl:torch.utils.data.dataloader.DataLoader, top:str, heavy_atoms:bool = True):
    r'''
Calculate rmsd, r2_score and MSE
--------------------------------
model : Trained model
dl : DataLoader
top (str) : Path to topology file
heavy_atoms (bool) : Caculate the fit-metrics only for heavy atoms if True, else calculte fit-metrics for all atoms
    '''
    top = md.load_topology(top)
    model.eval()
    k = dl.dataset.shape
    org_ = []
    pred_ = []
    rmsd_ = []

    with torch.no_grad():
        for batch in tqdm(dl, bar_format='calculating Fit-Metrics : {percentage:6.2f}% |{bar}|', ncols=50):
            pred_.append(model(batch).detach().cpu().numpy().reshape(-1,k[2],3))
            org_.append(batch.detach().cpu().numpy().reshape(-1,k[2],3))
            
        traj2 = md.Trajectory(np.concatenate(pred_), top)
        traj1 = md.Trajectory(np.concatenate(org_), top)
        del org_, pred_
        if heavy_atoms:
            ha = traj1.topology.select('not element H')
            traj2.superpose(traj1, frame=0, atom_indices=ha)
            for i in range(traj1.n_frames):
                rmsd_.append(md.rmsd(traj2[i], traj1[i], atom_indices=ha)[0])
        else:
            traj2.superpose(traj1, frame=0)
            for i in range(traj1.n_frames):
                rmsd_.append(md.rmsd(traj2[i], traj1[i]))
        
        arr = np.vstack([traj1.xyz.flatten('F'), traj2.xyz.flatten('F')]).T
        rmsd = np.array(rmsd_)*10 # convert to angstroms
    return rmsd, r2_score(arr[:,0], arr[:,1]), mean_squared_error(arr[:,0], arr[:,1])


class TrajectoryAnalysis:
    r'''
Cluster the trajectory
----------------------
trajectory (np.array) : Loaded trajectory in xyz format
    '''
    def __init__(self, trajectory):
        self.trajectory = trajectory
        self.n_frames, self.n_atoms, self.dim = self.trajectory.shape
        assert self.dim == 3, "The dimensions of each atom's coordinates should be 3."
        self.X = self.trajectory.reshape(self.n_frames, self.n_atoms * self.dim)
        self.pca = PCA(n_components=self.kaiser_criterion(), random_state=42)
        self.principal_components = self.pca.fit_transform(self.X)

    def clusters(self, n_clusters):
        kmeans = KMeans(n_clusters=n_clusters)
        kmeans.fit(self.principal_components)
        labels = kmeans.labels_

        clusters = {}
        for frame, cluster in enumerate(labels):
            if cluster not in clusters:
                clusters[cluster] = []
            clusters[cluster].append(frame)

        return clusters

    def plot_elbow_silhouette(self, max_clusters=10):
        distortions = []
        silhouette_scores = []

        for k in range(1, max_clusters + 1):
            kmeans = KMeans(n_clusters=k)
            kmeans.fit(self.principal_components)
            distortions.append(kmeans.inertia_)

            if k > 1:
                cluster_labels = kmeans.predict(self.principal_components)
                silhouette_avg = silhouette_score(self.principal_components, cluster_labels)
                silhouette_scores.append(silhouette_avg)

        fig, ax = plt.subplots(figsize=(5, 3.5))
        ax.scatter(range(1, max_clusters + 1), silhouette_scores, s=42, color='dodgerblue', label='Silhouette')
        ax.plot(range(1, max_clusters + 1), silhouette_scores, color='dodgerblue')
        ax.set_ylabel('Average Silhouette Score', family='serif', fontsize=12)
        ax.set_xlabel('Number of clusters', family='serif', fontsize=12)

        ax2 = ax.twinx()
        ax2.scatter(range(1, max_clusters + 1), distortions, s=42, color='pink', label='Elbow')
        ax2.plot(range(1, max_clusters + 1), distortions, color='pink')
        ax2.set_ylabel('Distortions', family='serif', fontsize=12)

        custom_lines = [plt.Line2D([0], [0], marker='o', color='dodgerblue', label='Silhouette'),
                        plt.Line2D([0], [0], marker='o', color='pink', label='Elbow')]
        ax.legend(handles=custom_lines, loc='upper right')
        plt.show()

    def kaiser_criterion(self):
        pca_ = PCA(n_components=3*self.n_atoms-6, random_state=42)
        pca_.fit(self.X)
        eigenvalues = pca_.explained_variance_
        n_components = np.sum(eigenvalues > 1)
        return n_components

def get_cluster(cluster):
    """
    Assigns cluster numbers to values in a dictionary of lists, where the cluster number
    corresponds to the key of the dictionary.
    
    Args:
        cluster (dict): A dictionary where the values are lists
    
    Returns:
        list: A list of cluster assignments for each value in ascending order from 0 to the maximum value.
    """
    all_values = []
    
    for key, values in cluster.items():
        all_values.extend(values)
    all_values.sort()
    
    cluster_assignments = []
    
    current_cluster = 0
    for value in all_values:
        for key, values in cluster.items():
            if value in values:
                cluster_assignments.append(key)
                break
    
    return cluster_assignments