import torch

from supr.pytorch.supr import SUPR

pose_params = torch.zeros((1, 75 * 3), dtype=torch.float32)
betas = torch.zeros((1, 10))
trans = torch.zeros((1, 3))

model_path = "/home/nshah/work/models/supr/supr_male.npy"
model = SUPR(model_path, num_betas=10)

out = model(pose_params, betas, trans)
for k, v in out.items():
    print(k, v.shape)
