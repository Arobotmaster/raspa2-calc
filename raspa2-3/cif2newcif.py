from pymatgen.io.cif import CifParser, CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

# 1. 读取原始 P1 CIF（primitive cell）
parser = CifParser("Cu-BTC_ASR_pacman.cif")
structure = parser.get_structures()[0]  # primitive cell :contentReference[oaicite:4]{index=4}

# 2. （可选）验证仍为 P1
sga = SpacegroupAnalyzer(structure, symprec=1e-3)
assert sga.get_space_group_symbol() == "P1"

# 3. 写出同样的 primitive cell，保留 _atom_site_charge
writer = CifWriter(
    structure,
    symprec=None,               # 不自动添加任何对称性信息 :contentReference[oaicite:5]{index=5}
    write_site_properties=True  # 写入 structure.site_properties['charge'] :contentReference[oaicite:6]{index=6}
)
writer.write_file("Cu-BTC_P1_primitive_charges.cif")
