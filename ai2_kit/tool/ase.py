import ase.io
from ase import Atoms
from typing import List, Union

class AseHelper:
    def __init__(self):
        self._atoms_list: List[Atoms] = []

    def read(self, filename: str, **kwargs):
        kwargs.setdefault('index', ':')
        data = ase.io.read(filename, **kwargs)
        if not isinstance(data, list):
            data = [data]
        self._atoms_list = data
        return self

    def write(self, filename: str, **kwargs):
        self._write(filename, self._atoms_list, **kwargs)

    def set_cell(self, cell, scale_atoms=False, apply_constraint=True):
        for atoms in self._atoms_list:
            atoms.set_cell(cell, scale_atoms=scale_atoms, apply_constraint=apply_constraint)
        return self

    def set_pbc(self, pbc):
        for atoms in self._atoms_list:
            atoms.set_pbc(pbc)
        return self

    def delete_atoms(self, id: Union[int, List[int]]):
        ids = [id] if isinstance(id, int) else id
        for atoms in self._atoms_list:
            for i in sorted(ids, reverse=True):
                del atoms[i]
        return self

    def write_each_frame(self, filename: str, **kwargs):
        for i, atoms in enumerate(self._atoms_list):
            self._write(filename.format(i=i), atoms, **kwargs)

    def _write(self, filename: str, atoms_list, **kwargs):
        fmt = kwargs.get('format', None)
        if fmt == 'lammps-dump-text':
            return self._write_lammps_dump_text(filename, atoms_list, **kwargs)
        return ase.io.write(filename, atoms_list, **kwargs)

    def _write_lammps_dump_text(self, filename: str, atoms_list, **kwargs):
        if not isinstance(atoms_list, list):
            atoms_list = [atoms_list]
        type_map = kwargs.get('type_map', None)
        lines = []
        for i, atoms in enumerate(atoms_list):
            lines += [
                "ITEM: TIMESTEP", str(i),
                "ITEM: NUMBER OF ATOMS", str(len(atoms)),
            ]
            # It is kind of hacky to set boundary and cell in this way.
            # TODO: refactor it in the future.
            pbc = atoms.get_pbc()
            boundary =  ' '.join(['pp' if b else 'ff' for b in pbc])
            cell = atoms.get_cell()
            lines += [
                f"ITEM: BOX BOUNDS xy xz yz {boundary}",
                "%.16e %.16e %.16e" % (0, cell[0][0], 0),
                "%.16e %.16e %.16e" % (0, cell[1][1], 0),
                "%.16e %.16e %.16e" % (0, cell[2][2], 0),
                # TODO: support more properties, forces for example
                "ITEM: ATOMS id type x y z",
            ]

            for j, atom in enumerate(atoms):
                pos = atom.position
                no = atom.number if type_map is None else type_map.index(atom.symbol) + 1
                lines.append("%3d %2s %10.5f %10.5f %10.5f" % (j+1, no , pos[0], pos[1], pos[2]))

        with open(filename, 'w') as f:
            f.write('\n'.join(lines))
