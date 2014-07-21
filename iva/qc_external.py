import subprocess
import tempfile
import shutil
import os
import sys
import inspect
import fastaq
from iva import common

class Error (Exception): pass

gage_stats = [
    'Missing Reference Bases',
    'Missing Assembly Bases',
    'Missing Assembly Contigs',
    'Duplicated Reference Bases',
    'Compressed Reference Bases',
    'Bad Trim',
    'Avg Idy',
    'SNPs',
    'Indels < 5bp',
    'Indels >= 5',
    'Inversions',
    'Relocation',
    'Translocation',
]


ratt_stats = [
     'elements_found',
     'elements_transferred',
     'elements_transferred_partially',
     'elements_split',
     'parts_of_elements_not_transferred',
     'elements_not_transferred',
     'gene_models_to_transfer',
     'gene_models_transferred',
     'gene_models_transferred_partially',
     'exons_not_transferred_from_partial_matches',
     'gene_models_not_transferred',
]

default_ratt_config = os.path.join(os.path.dirname(inspect.getfile(inspect.currentframe())), 'ratt', 'ratt.config')


def dummy_gage_stats():
    return {x:'NA' for x in gage_stats}


def dummy_ratt_stats():
    return {x:'NA' for x in ratt_stats}


def run_gage(reference, scaffolds, outdir, nucmer_minid=80, clean=True):
    this_module_dir = os.path.dirname(inspect.getfile(inspect.currentframe()))
    gage_dir = os.path.join(this_module_dir, 'gage')
    reference = os.path.abspath(reference)
    scaffolds = os.path.abspath(scaffolds)
    ref = 'ref.fa'
    scaffs = 'scaffolds.fa'
    contigs = 'contigs.fa'
    gage_out = 'gage.out'
    gage_script = 'run.sh'
    cwd = os.getcwd()
    os.mkdir(outdir)
    os.chdir(outdir)
    os.symlink(reference, ref)
    os.symlink(scaffolds, scaffs)
    fastaq.tasks.scaffolds_to_contigs(scaffs, contigs, number_contigs=True)
    f = fastaq.utils.open_file_write(gage_script)
    print(' '.join([
        'sh',
        os.path.join(gage_dir, 'getCorrectnessStats.sh'),
        ref,
        contigs,
        scaffs,
        str(nucmer_minid),
        '>', gage_out
        ]), file=f)
    fastaq.utils.close(f)
    common.syscall('bash ' + gage_script)
    stats = dummy_gage_stats()
    wanted_stats = set(gage_stats)
    f = fastaq.utils.open_file_read(gage_out)

    for line in f:
        if line.startswith('Corrected Contig Stats'):
            break
        elif ':' in line:
            a = line.rstrip().split(': ')
            if a[0] in wanted_stats:
                stat = a[1]
                if '%' in stat:
                    stat = stat.split('(')[0]
                if stat.isdigit():
                    stats[a[0]] = int(stat)
                else:
                    stats[a[0]] = float(stat)
    fastaq.utils.close(f)

    if clean:
        to_clean = [
            'contigs.fa.delta',
            'contigs.fa.fdelta',
            'contigs.fa.matches.lens',
            'out.1coords',
            'out.1delta',
            'out.mcoords',
            'out.mdelta',
            'out.qdiff',
            'out.rdiff',
            'out.snps',
            'out.unqry',
            'scaffolds.fa.coords',
            'scaffolds.fa.delta',
            'scaffolds.fa.err',
            'scaffolds.fa.fdelta',
            'scaffolds.fa.tiling',
            'tmp_scf.fasta',
        ]
        for f in to_clean:
            try:
                os.unlink(f)
            except:
                pass

    os.chdir(cwd)
    return stats


def run_ratt(embl_dir, assembly, outdir, config_file=None, transfer='Species', clean=True):
    embl_dir = os.path.abspath(embl_dir)
    assembly = os.path.abspath(assembly)
    this_module_dir =os.path.dirname(inspect.getfile(inspect.currentframe()))
    ratt_dir = os.path.join(this_module_dir, 'ratt')
    if config_file is None:
        ratt_config = default_ratt_config
    else:
        ratt_config = os.path.abspath(config_file)

    cwd = os.getcwd()
    try:
        os.mkdir(outdir)
        os.chdir(outdir)
    except:
        raise Error('Error mkdir ' + outdir)

    script = 'run.sh'
    script_out = 'run.sh.out'
    ratt_outprefix = 'out'
    f = fastaq.utils.open_file_write(script)
    print('export RATT_HOME=', ratt_dir, sep='', file=f)
    print('export RATT_CONFIG=', ratt_config, sep='', file=f)
    print('$RATT_HOME/start.ratt.sh', embl_dir, assembly, ratt_outprefix, transfer, file=f)
    fastaq.utils.close(f)
    cmd = 'bash ' + script + ' > ' + script_out
    # sometimes ratt returns nonzero code, but is OK, so ignore it
    common.syscall(cmd, allow_fail=True)

    stats = {}

    matches = {
        'elements found.': 'elements_found',
        'Elements were transfered.': 'elements_transferred',
        'Elements could be transfered partially.': 'elements_transferred_partially',
        'Elements split.': 'elements_split',
        'Parts of elements (i.e.exons tRNA) not transferred.': 'parts_of_elements_not_transferred',
        'Elements couldn\'t be transferred.': 'elements_not_transferred',
        'Gene models to transfer.': 'gene_models_to_transfer',
        'Gene models transferred correctly.': 'gene_models_transferred',
        'Gene models partially transferred.': 'gene_models_transferred_partially',
        'Exons not transferred from partial CDS matches.': 'exons_not_transferred_from_partial_matches',
        'Gene models not transferred.': 'gene_models_not_transferred',
    }

    f = fastaq.utils.open_file_read(script_out)
    for line in f:
        if '\t' in line:
            a = line.rstrip().split('\t')
            if len(a) == 2 and a[0].isdigit() and a[1] in matches:
                stats[matches[a[1]]] = int(a[0])
    fastaq.utils.close(f)

    if clean:
        for d in ['Query', 'Reference', 'Sequences']:
            try:
                shutil.rmtree(d)
            except:
                pass

        common.syscall('rm query.* Reference.* nucmer.* out.*')

    os.chdir(cwd)
    return stats


def run_blastn_and_write_act_script(assembly, reference, blast_out, script_out):
    tmpdir = tempfile.mkdtemp(prefix='tmp.blastn.', dir=os.getcwd())
    assembly_union = os.path.join(tmpdir, 'assembly.union.fa')
    reference_union = os.path.join(tmpdir, 'reference.union.fa')
    fastaq.tasks.to_fasta_union(assembly, assembly_union, seqname='assembly_union')
    fastaq.tasks.to_fasta_union(reference, reference_union, seqname='reference_union')
    common.syscall('makeblastdb -dbtype nucl -in ' + reference_union)
    cmd = ' '.join([
        'blastn',
        '-task blastn',
        '-db', reference_union,
        '-query', assembly_union,
        '-out', blast_out,
        '-outfmt 6',
        '-evalue 0.01',
        '-dust no',
    ])
    common.syscall(cmd)

    f = fastaq.utils.open_file_write(script_out)
    print('#!/usr/bin/env bash', file=f)
    print('act', reference, blast_out, assembly, file=f)
    fastaq.utils.close(f)
    common.syscall('chmod 755 ' + script_out)
    shutil.rmtree(tmpdir)
