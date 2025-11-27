"""
EPG Consolidator - Manages the EPG file pipeline

File structure:
  /data/teams.xml         - Team-based EPG (one channel per team)
  /data/event_epg_*.xml   - Per-group event EPG files
  /data/events.xml        - All event EPGs merged
  /data/teamarr.xml       - Final combined EPG (teams + events)

Flow:
  Team generation  → teams.xml  ─┐
                                 ├─→ teamarr.xml
  Event generation → events.xml ─┘
"""

import os
import glob
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Default data directory
DEFAULT_DATA_DIR = '/app/data'


def get_data_dir() -> str:
    """Get data directory, preferring /app/data for Docker."""
    if os.path.exists('/app/data'):
        return '/app/data'
    # Fallback to project's data dir
    base_dir = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base_dir, 'data')


def get_epg_paths(final_output_path: str = None) -> Dict[str, str]:
    """
    Get all EPG file paths.

    Args:
        final_output_path: Override for final merged output (from settings)
    """
    data_dir = get_data_dir()

    # Final output path from settings or default
    if not final_output_path:
        final_output_path = os.path.join(data_dir, 'teamarr.xml')

    return {
        'teams': os.path.join(data_dir, 'teams.xml'),
        'events': os.path.join(data_dir, 'events.xml'),
        'combined': final_output_path,
        'data_dir': data_dir
    }


def consolidate_event_epgs() -> Dict[str, Any]:
    """
    Merge all event_epg_*.xml files into events.xml.

    Returns:
        Dict with success status and stats
    """
    from epg.event_epg_generator import merge_xmltv_files

    paths = get_epg_paths()
    data_dir = paths['data_dir']

    # Find all event EPG files
    pattern = os.path.join(data_dir, 'event_epg_*.xml')
    event_files = glob.glob(pattern)

    if not event_files:
        logger.info("No event EPG files to consolidate")
        # Create empty events.xml if no event files exist
        empty_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE tv SYSTEM "xmltv.dtd">
<tv generator-info-name="Teamarr Event EPG">
</tv>'''
        os.makedirs(data_dir, exist_ok=True)
        with open(paths['events'], 'w') as f:
            f.write(empty_xml)
        return {
            'success': True,
            'files_merged': 0,
            'output_path': paths['events']
        }

    logger.info(f"Consolidating {len(event_files)} event EPG files")

    result = merge_xmltv_files(
        file_paths=event_files,
        output_path=paths['events'],
        generator_name="Teamarr Event EPG"
    )

    return result


def merge_all_epgs(final_output_path: str = None) -> Dict[str, Any]:
    """
    Merge teams.xml and events.xml into final output.

    This is the final merge step that creates the combined EPG
    served to Dispatcharr.

    Args:
        final_output_path: Final destination (from settings' epg_output_path)

    Returns:
        Dict with success status and stats
    """
    from epg.event_epg_generator import merge_xmltv_files

    paths = get_epg_paths(final_output_path)

    # Collect files that exist
    files_to_merge = []

    if os.path.exists(paths['teams']):
        files_to_merge.append(paths['teams'])
        logger.debug(f"Including teams.xml in merge")

    if os.path.exists(paths['events']):
        files_to_merge.append(paths['events'])
        logger.debug(f"Including events.xml in merge")

    if not files_to_merge:
        logger.warning("No EPG files to merge - creating empty teamarr.xml")
        empty_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE tv SYSTEM "xmltv.dtd">
<tv generator-info-name="Teamarr">
</tv>'''
        os.makedirs(paths['data_dir'], exist_ok=True)
        with open(paths['combined'], 'w') as f:
            f.write(empty_xml)
        return {
            'success': True,
            'files_merged': 0,
            'output_path': paths['combined']
        }

    logger.info(f"Merging {len(files_to_merge)} EPG files into teamarr.xml")

    result = merge_xmltv_files(
        file_paths=files_to_merge,
        output_path=paths['combined'],
        generator_name="Teamarr"
    )

    if result.get('success'):
        logger.info(f"Combined EPG: {result.get('channel_count')} channels, {result.get('programme_count')} programmes")

    return result


def after_team_epg_generation(xml_content: str, final_output_path: str = None) -> Dict[str, Any]:
    """
    Called after team EPG is generated.

    Saves to teams.xml (hardcoded) then triggers merge to final output.

    Args:
        xml_content: Generated team XMLTV content
        final_output_path: Final merged destination (from settings' epg_output_path)

    Returns:
        Dict with file paths and merge result
    """
    paths = get_epg_paths(final_output_path)

    # Save to teams.xml (hardcoded)
    os.makedirs(paths['data_dir'], exist_ok=True)
    with open(paths['teams'], 'w', encoding='utf-8') as f:
        f.write(xml_content)
    logger.info(f"Saved team EPG to {paths['teams']}")

    # Trigger final merge
    merge_result = merge_all_epgs(final_output_path)

    return {
        'teams_path': paths['teams'],
        'combined_path': paths['combined'],
        'merge_result': merge_result
    }


def after_event_epg_generation(group_id: int = None, final_output_path: str = None) -> Dict[str, Any]:
    """
    Called after event EPG is generated for a group.

    Consolidates all event_epg_*.xml → events.xml (hardcoded) then merges to final output.

    Args:
        group_id: Optional group ID that was just generated (for logging)
        final_output_path: Final merged destination (from settings' epg_output_path)

    Returns:
        Dict with consolidation and merge results
    """
    if group_id:
        logger.info(f"Event EPG updated for group {group_id}, consolidating...")

    # Consolidate all event_epg_*.xml → events.xml (hardcoded)
    consolidate_result = consolidate_event_epgs()

    if not consolidate_result.get('success'):
        return {
            'success': False,
            'error': f"Consolidation failed: {consolidate_result.get('error')}",
            'consolidate_result': consolidate_result
        }

    # Trigger final merge
    merge_result = merge_all_epgs(final_output_path)

    paths = get_epg_paths(final_output_path)
    return {
        'success': merge_result.get('success', False),
        'events_path': paths['events'],
        'combined_path': paths['combined'],
        'consolidate_result': consolidate_result,
        'merge_result': merge_result
    }


def get_epg_stats() -> Dict[str, Any]:
    """
    Get statistics about current EPG files.

    Returns:
        Dict with file info and stats
    """
    import xml.etree.ElementTree as ET

    paths = get_epg_paths()
    stats = {}

    for name, path in paths.items():
        if name == 'data_dir':
            continue

        if os.path.exists(path):
            try:
                tree = ET.parse(path)
                root = tree.getroot()
                stats[name] = {
                    'exists': True,
                    'path': path,
                    'size': os.path.getsize(path),
                    'channels': len(root.findall('channel')),
                    'programmes': len(root.findall('programme')),
                    'modified': os.path.getmtime(path)
                }
            except Exception as e:
                stats[name] = {
                    'exists': True,
                    'path': path,
                    'error': str(e)
                }
        else:
            stats[name] = {
                'exists': False,
                'path': path
            }

    # Count event EPG files
    pattern = os.path.join(paths['data_dir'], 'event_epg_*.xml')
    event_files = glob.glob(pattern)
    stats['event_group_files'] = len(event_files)

    return stats
