#! /usr/bin/env python
'''Deduplicates BAM file based on custom inline DNA barcodes.
Emits a new BAM file reduced to a single consensus read for each family of
original reads.'''
##   Copyright 2014 Bioinformatics Core, University of Michigan
##
##   Licensed under the Apache License, Version 2.0 (the "License");
##   you may not use this file except in compliance with the License.
##   You may obtain a copy of the License at
##
##       http://www.apache.org/licenses/LICENSE-2.0
##
##   Unless required by applicable law or agreed to in writing, software
##   distributed under the License is distributed on an "AS IS" BASIS,
##   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
##   See the License for the specific language governing permissions and
##   limitations under the License.
from __future__ import print_function, absolute_import, division
from collections import defaultdict
import sys
import pysam


class LightweightAlignment(object):
    '''Minimal info from PySam.AlignedSegment used to expedite pos grouping.'''
    def __init__(self, aligned_segment):
        self.name = aligned_segment.query_name
        chrom = aligned_segment.reference_name
        pos1 = aligned_segment.reference_start
        pos2 = aligned_segment.next_reference_start
        if pos1 < pos2:
            self.key = (chrom, pos1, pos2)
        else:
            self.key = (chrom, pos2, pos1)


class PairedAlignment(object):
    '''Represents the left and right align pairs from an single sequence.'''
    def __init__(self, left_alignment, right_alignment):
        self.left_alignment = left_alignment
        self.right_alignment = right_alignment

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __hash__(self):
        return hash(self.left_alignment) * hash(self.right_alignment)

    def __repr__(self):
        return ("Pair({}|{}|{}, "
                "{}|{}|{})").format(self.left_alignment.query_name, 
                                    self.left_alignment.reference_start,
                                    self.left_alignment.query_sequence,
                                    self.right_alignment.query_name, 
                                    self.right_alignment.reference_start,
                                    self.right_alignment.query_sequence)

def _build_coordinate_read_name_manifest(lw_aligns):
    '''Return a dict mapping coordinates to set of aligned querynames.

    Constructed on a preliminary pass through the input BAM, this lightweight
    dict informs downstream processing that the collection of reads at a 
    coordinate can be released.
    '''
    af_dict = defaultdict(set)
    for lwa in lw_aligns:
        af_dict[lwa.key].add(lwa.name)
    return af_dict

def _build_coordinate_families(aligned_segments,coord_read_name_manifest):
    '''Generate sets of PairedAlignments that share the same coordinates.'''
    family_dict = defaultdict(set)
    pairing_dict = {}
    for aseg in aligned_segments:
        if not aseg.query_name in pairing_dict:
            pairing_dict[aseg.query_name]= aseg
        else:
            paired_align = PairedAlignment(pairing_dict.pop(aseg.query_name),
                                           aseg)
            key = LightweightAlignment(aseg).key
            family_dict[key].add(paired_align)
            coord_read_name_manifest[key].remove(aseg.query_name)
            if not coord_read_name_manifest[key]:
                yield family_dict.pop(key)

def _build_consensus_pair(alignment_family):
    '''Aggregate a set of reads into a single consensus read.'''
    return alignment_family.pop()


def _build_tag_families(tagged_paired_aligns, ranked_tags):
    '''Return a list of read families; each family is a set of original reads.
    
    Each read is considered against each ranked tag until all reads are
    partitioned into families.'''
    tag_aligns = defaultdict(set)
    for paired_align in tagged_paired_aligns:
        left_tag_id =  paired_align.left_alignment.query_sequence[0:3]
        right_tag_id =  paired_align.right_alignment.query_sequence[0:3]
        for best_tag in ranked_tags:
            if left_tag_id == best_tag[0] or right_tag_id == best_tag[1]:
                tag_aligns[best_tag].add(paired_align)
                break
    return tag_aligns.values()

def _rank_tags(tagged_paired_aligns):
    '''Return the list of tags ranked from most to least popular.'''
    tag_count = defaultdict(int)
    for paired_align in tagged_paired_aligns:
        left_tag_id = paired_align.left_alignment.query_sequence[0:3]
        right_tag_id = paired_align.right_alignment.query_sequence[0:3]
        tag_count[(left_tag_id, right_tag_id)] += 1
    tags_by_count = sorted(tag_count.items(),
                           key=lambda x: (-1 * x[1], x[0]))
    ranked_tags = [tag_count[0] for (tag_count) in tags_by_count]
    return ranked_tags

def main(input_bam, output_bam):
    '''Connor entry point.  See help for more info'''
    bamfile = pysam.AlignmentFile(input_bam, "rb")
    lw_aligns = [LightweightAlignment(align) for align in bamfile.fetch()]
    coord_manifest = _build_coordinate_read_name_manifest(lw_aligns)
    bamfile.close()
    bamfile = pysam.AlignmentFile(input_bam, "rb")
    outfile = pysam.AlignmentFile(output_bam, "wb", template=bamfile)
    for coord_family in _build_coordinate_families(bamfile.fetch(),
                                                   coord_manifest):
        ranked_tags = _rank_tags(coord_family)
        for tag_family in _build_tag_families(coord_family, ranked_tags):
            read_pair = _build_consensus_pair(tag_family)
            outfile.write(read_pair.left_alignment)
            outfile.write(read_pair.right_alignment)
    outfile.close()
    bamfile.close()

if __name__ == '__main__':
    in_bam = sys.argv[1]
    out_bam = sys.argv[2]
    main(in_bam, out_bam)
