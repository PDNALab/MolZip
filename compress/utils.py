import mdtraj as md
import numpy as np
import os
from tqdm import tqdm
import time
from compress import *

# import sys
from torch.utils.data import DataLoader

def read_traj_to_dl(traj_:str, top_:str, memmap:bool=False, stride:int=None, chunk:int=1000, batch_size:int=128):
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
        
    with md.open(traj_, 'r') as t:  # Open in read-only mode
        n_frames = t.n_frames
        n_atoms = t.n_atoms

    print(f'\nTrajectory stats : #_Frames = {n_frames}\t#_Atoms = {n_atoms}')
    print('_'*70,'\n')
    print(f'Start reading coordinates from trajectory to train model...\n[{int(n_frames/stride)} frames with stride {stride}]')

    if memmap:
        centered_xyz = np.memmap('temp_traj.dat', dtype=np.float32, mode='w+', shape=(int(n_frames/stride), n_atoms, 3))
    else:
        centered_xyz = np.empty(dtype=np.float32, shape=(int(n_frames/stride), n_atoms, 3))
      
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
        

    traj_dl = DataLoader(centered_xyz.reshape(-1,1,n_atoms,3), batch_size=batch_size, shuffle=True, drop_last=True)
    if stride != None:
        print(f'\nDataLoader created')
    print('_'*70,'\n')
    
    del centered_xyz

    if memmap:
        os.remove('temp_traj.dat')

    return traj_dl, n_atoms

def rmsd_validation(model:LightAE, dl:torch.utils.data.dataloader.DataLoader, top:str, heavy_atoms:bool = True):
    top = md.load_topology(top)
    model.eval()
    rmsd = []

    with torch.no_grad():
        for batch in tqdm(dl, bar_format='calculating RMSD : {percentage:6.2f}% |{bar}|', ncols=50):
            pred_ = model(batch)
            for y, y_ in zip(batch, pred_):
                traj1 = md.Trajectory(y.detach().cpu().numpy().reshape(-1,3), top)
                traj2 = md.Trajectory(y_.detach().cpu().numpy().reshape(-1,3), top)
                if heavy_atoms:
                    ha = traj1.topology.select('not element H')
                    traj2.superpose(traj1, frame=0, atom_indices=ha)
                    rmsd_value = md.rmsd(traj2, traj1, atom_indices=ha)
                else:
                    traj2.superpose(traj1, frame=0)
                    rmsd_value = md.rmsd(traj2, traj1)
                rmsd.append(float(rmsd_value[0]))
    return np.array(rmsd) 