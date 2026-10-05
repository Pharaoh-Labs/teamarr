"""Frozen copies of the starter templates as earlier releases shipped them.

The seed upgrades a starter in place only when its row still equals something
we shipped. Older generations were rebuilt by reverting individual edits from
the live spec; the style pass rewrote too much text for that, so the starters
as they stood immediately before it are kept here verbatim and the older
chain is derived from this copy.

Generated from DEFAULT_TEMPLATE_SET — never edit by hand.
"""
# ruff: noqa: E501

PRE_STYLE_PASS: dict[str, dict] = {'Default Team (Starter)': {'template_type': 'team',
                            'team_channel_name': '{league} | {team_name}',
                            'title_format': '{gracenote_category}',
                            'subtitle_template': '{team1} {at_vs} {team2}',
                            'program_art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=1&logo=true&fallback=true',
                            'team_channel_logo_url': '{league_id}/{team_name|pascal}/logo.png?style=1&logo=true&fallback=true',
                            'game_duration_mode': 'sport',
                            'pregame_enabled': True,
                            'postgame_enabled': True,
                            'idle_enabled': True,
                            'xmltv_flags': {'new': True, 'live': True, 'date': True},
                            'xmltv_video': {'enabled': False, 'quality': 'HDTV'},
                            'xmltv_categories': ['Sports', '{sport}', 'Sports event'],
                            'xmltv_filler_categories': [],
                            'pregame_periods': [],
                            'pregame_fallback': {'title': 'Coming up: {gracenote_category} at '
                                                          '{game_time.next}',
                                                 'subtitle': '{team1.next} {at_vs.next} '
                                                             '{team2.next}',
                                                 'description': '{game_preview.next}',
                                                 'description_fallback': 'The '
                                                                         '{away_team_record.next} '
                                                                         '{away_team.next} travel '
                                                                         'to {venue_city.next}, '
                                                                         '{venue_state.next} to '
                                                                         'play the '
                                                                         '{home_team_record.next} '
                                                                         '{home_team.next} '
                                                                         '{today_tonight.next} at '
                                                                         '{game_time.next}.',
                                                 'art_url': '{league_id}/{away_team.next|pascal}/{home_team.next|pascal}/cover.png?style=1&logo=true&fallback=true'},
                            'postgame_periods': [],
                            'postgame_fallback': {'title': '{gracenote_category}: Final',
                                                  'subtitle': '{team1.last} {at_vs.last} '
                                                              '{team2.last}',
                                                  'description': '{team_name_the} '
                                                                 '{result_text.last} '
                                                                 '{opponent_the.last} '
                                                                 '{final_score.last}',
                                                  'art_url': '{league_id}/{away_team.last|pascal}/{home_team.last|pascal}/cover.png?style=1&logo=true&fallback=true'},
                            'postgame_conditional': {'enabled': False,
                                                     'description_final': None,
                                                     'description_not_final': None},
                            'postgame_conditional_rows': [{'condition': 'has_recap',
                                                           'condition_value': None,
                                                           'template': '{game_recap.last}',
                                                           'priority': 10,
                                                           'label': 'Recap (provider)'},
                                                          {'condition': 'is_not_final',
                                                           'condition_value': None,
                                                           'template': 'The game between '
                                                                       '{team_name_the} and '
                                                                       '{opponent_the.last} has '
                                                                       'not yet ended as of the '
                                                                       'last update.',
                                                           'priority': 50,
                                                           'label': 'In progress'}],
                            'idle_content': {'title': 'No {team_name} Game Today',
                                             'subtitle': 'Next game: {game_date.next} at '
                                                         '{game_time.next} {vs_at.next} '
                                                         '{opponent_the.next}',
                                             'description': 'Next game: {game_date.next} at '
                                                            '{game_time.next}. The '
                                                            '{away_team_record.next} '
                                                            '{away_team.next} travel to '
                                                            '{venue_city.next}, {venue_state.next} '
                                                            'to play the {home_team_record.next} '
                                                            '{home_team.next} at {venue.next}.',
                                             'art_url': ''},
                            'idle_conditional': {'enabled': False,
                                                 'description_final': None,
                                                 'description_not_final': None},
                            'idle_conditional_rows': [{'condition': 'is_final',
                                                       'condition_value': None,
                                                       'template': '{team_name_the} '
                                                                   '{result_text.last} '
                                                                   '{opponent_the.last} '
                                                                   '{final_score.last} '
                                                                   '{overtime_text.last} on '
                                                                   '{game_date.last}. Next game '
                                                                   'will be with '
                                                                   '{opponent_the.next} on '
                                                                   '{game_date.next} at '
                                                                   '{game_time.next}.',
                                                       'priority': 50,
                                                       'label': 'Final'},
                                                      {'condition': 'is_not_final',
                                                       'condition_value': None,
                                                       'template': '{team_name_the} last played '
                                                                   'against {opponent_the.last} on '
                                                                   '{game_date.last}. Next game '
                                                                   'will be with '
                                                                   '{opponent_the.next} on '
                                                                   '{game_date.next} at '
                                                                   '{game_time.next}.',
                                                       'priority': 50,
                                                       'label': 'In progress'}],
                            'pregame_conditional_rows': [],
                            'idle_offseason': {'title_enabled': False,
                                               'title': None,
                                               'subtitle_enabled': True,
                                               'subtitle': 'No upcoming game currently on schedule '
                                                           'in next 30 days',
                                               'description_enabled': True,
                                               'description': 'No upcoming {team_name} games '
                                                              'scheduled.'},
                            'conditional_descriptions': [{'condition': 'has_preview',
                                                          'condition_value': None,
                                                          'template': '{game_preview}',
                                                          'priority': 10,
                                                          'label': 'Preview (provider)'},
                                                         {'condition': 'has_event_note',
                                                          'condition_value': None,
                                                          'template': '{game_event_note}. The '
                                                                      '{away_team_record} '
                                                                      '{away_team} and the '
                                                                      '{home_team_record} '
                                                                      '{home_team} meet at '
                                                                      '{venue}.',
                                                          'priority': 15,
                                                          'label': 'Marquee note'},
                                                         {'condition': 'is_neutral_site',
                                                          'condition_value': None,
                                                          'template': 'The {away_team_record} '
                                                                      '{away_team} and the '
                                                                      '{home_team_record} '
                                                                      '{home_team} meet at '
                                                                      '{venue}. '
                                                                      '{last_five_summary} '
                                                                      '{series_summary}',
                                                          'priority': 17,
                                                          'label': 'Neutral site'},
                                                         {'condition': 'has_structured_preview',
                                                          'condition_value': None,
                                                          'template': 'The {away_team_record} '
                                                                      '{away_team} travel to '
                                                                      '{venue_city}, {venue_state} '
                                                                      'to play the '
                                                                      '{home_team_record} '
                                                                      '{home_team} at {venue}. '
                                                                      '{last_five_summary} '
                                                                      '{series_summary}',
                                                          'priority': 20,
                                                          'label': 'Structured preview'},
                                                         {'condition': None,
                                                          'condition_value': None,
                                                          'template': 'The {away_team_record} '
                                                                      '{away_team} travel to '
                                                                      '{venue_city}, {venue_state} '
                                                                      'to play the '
                                                                      '{home_team_record} '
                                                                      '{home_team} at {venue}.',
                                                          'priority': 100,
                                                          'label': 'Default'}],
                            'event_channel_name': '{team_name}',
                            'event_channel_logo_url': '',
                            'name': 'Default Team (Starter)'},
 'Soccer Team (Starter)': {'template_type': 'team',
                           'team_channel_name': '{league} | {team_name}',
                           'title_format': '{gracenote_category}',
                           'subtitle_template': '{team1} vs {team2}',
                           'program_art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=1&logo=true&fallback=true',
                           'team_channel_logo_url': '{league_id}/{team_name|pascal}/logo.png?style=1&logo=true&fallback=true',
                           'game_duration_mode': 'sport',
                           'pregame_enabled': True,
                           'postgame_enabled': True,
                           'idle_enabled': True,
                           'xmltv_flags': {'new': True, 'live': True, 'date': True},
                           'xmltv_video': {'enabled': False, 'quality': 'HDTV'},
                           'xmltv_categories': ['Sports', '{sport}', 'Sports event'],
                           'xmltv_filler_categories': [],
                           'pregame_periods': [],
                           'pregame_fallback': {'title': 'Coming up: {gracenote_category} at '
                                                         '{game_time.next}',
                                                'subtitle': '{team1.next} vs {team2.next}',
                                                'description': '{game_preview.next}',
                                                'description_fallback': '{away_team_the.next} face '
                                                                        '{home_team_the.next} at '
                                                                        '{venue.next} '
                                                                        '{today_tonight.next} at '
                                                                        '{game_time.next}.',
                                                'art_url': '{league_id}/{away_team.next|pascal}/{home_team.next|pascal}/cover.png?style=1&logo=true&fallback=true'},
                           'postgame_periods': [],
                           'postgame_fallback': {'title': '{gracenote_category}: Full Time',
                                                 'subtitle': '{team1.last} {at_vs.last} '
                                                             '{team2.last}',
                                                 'description': '{team_name_the} '
                                                                '{result_text.last} '
                                                                '{opponent_the.last} '
                                                                '{final_score.last}',
                                                 'art_url': '{league_id}/{away_team.last|pascal}/{home_team.last|pascal}/cover.png?style=1&logo=true&fallback=true'},
                           'postgame_conditional': {'enabled': False,
                                                    'description_final': None,
                                                    'description_not_final': None},
                           'postgame_conditional_rows': [{'condition': 'has_recap',
                                                          'condition_value': None,
                                                          'template': '{game_recap.last}',
                                                          'priority': 10,
                                                          'label': 'Recap (provider)'},
                                                         {'condition': 'is_not_final',
                                                          'condition_value': None,
                                                          'template': 'The game between '
                                                                      '{team_name_the} and '
                                                                      '{opponent_the.last} has not '
                                                                      'yet ended as of the last '
                                                                      'update.',
                                                          'priority': 50,
                                                          'label': 'In progress'}],
                           'idle_content': {'title': 'No {team_name} Match Today',
                                            'subtitle': 'Next match: {game_date.next} at '
                                                        '{game_time.next} {vs_at.next} '
                                                        '{opponent_the.next}',
                                            'description': 'Next match: {game_date.next} at '
                                                           '{game_time.next}. {away_team_the.next} '
                                                           'face {home_team_the.next} at '
                                                           '{venue.next}.',
                                            'art_url': ''},
                           'idle_conditional': {'enabled': False,
                                                'description_final': None,
                                                'description_not_final': None},
                           'idle_conditional_rows': [{'condition': 'is_final',
                                                      'condition_value': None,
                                                      'template': '{team_name_the} '
                                                                  '{result_text.last} '
                                                                  '{opponent_the.last} '
                                                                  '{final_score.last} on '
                                                                  '{game_date.last}. Next match is '
                                                                  'against {opponent_the.next} on '
                                                                  '{game_date.next} at '
                                                                  '{game_time.next}.',
                                                      'priority': 50,
                                                      'label': 'Final'},
                                                     {'condition': 'is_not_final',
                                                      'condition_value': None,
                                                      'template': '{team_name_the} last played '
                                                                  '{opponent_the.last} on '
                                                                  '{game_date.last}. Next match is '
                                                                  'against {opponent_the.next} on '
                                                                  '{game_date.next} at '
                                                                  '{game_time.next}.',
                                                      'priority': 50,
                                                      'label': 'In progress'}],
                           'pregame_conditional_rows': [],
                           'idle_offseason': {'title_enabled': False,
                                              'title': None,
                                              'subtitle_enabled': True,
                                              'subtitle': 'No upcoming match currently on schedule '
                                                          'in next 30 days',
                                              'description_enabled': True,
                                              'description': 'No upcoming {team_name} matches '
                                                             'scheduled.'},
                           'conditional_descriptions': [{'condition': 'has_preview',
                                                         'condition_value': None,
                                                         'template': '{game_preview}',
                                                         'priority': 10,
                                                         'label': 'Preview (provider)'},
                                                        {'condition': 'has_match_note',
                                                         'condition_value': None,
                                                         'template': '{soccer_match_note}. '
                                                                     '{away_team_the} face '
                                                                     '{home_team_the} at {venue}.',
                                                         'priority': 15,
                                                         'label': 'Competition note'},
                                                        {'condition': 'has_structured_preview',
                                                         'condition_value': None,
                                                         'template': '{away_team_the} face '
                                                                     '{home_team_the} at {venue}. '
                                                                     '{last_five_summary} '
                                                                     '{series_summary}',
                                                         'priority': 20,
                                                         'label': 'Structured preview'},
                                                        {'condition': None,
                                                         'condition_value': None,
                                                         'template': '{away_team_the} face '
                                                                     '{home_team_the} at {venue}.',
                                                         'priority': 100,
                                                         'label': 'Default'}],
                           'event_channel_name': '{team_name}',
                           'event_channel_logo_url': '',
                           'name': 'Soccer Team (Starter)'},
 'College Team (Starter)': {'template_type': 'team',
                            'team_channel_name': '{league} | {team_name}',
                            'title_format': '{gracenote_category}',
                            'subtitle_template': '{team1} {at_vs} {team2}',
                            'program_art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=1&logo=true&fallback=true',
                            'team_channel_logo_url': '{league_id}/{team_name|pascal}/logo.png?style=1&logo=true&fallback=true',
                            'game_duration_mode': 'sport',
                            'pregame_enabled': True,
                            'postgame_enabled': True,
                            'idle_enabled': True,
                            'xmltv_flags': {'new': True, 'live': True, 'date': True},
                            'xmltv_video': {'enabled': False, 'quality': 'HDTV'},
                            'xmltv_categories': ['Sports', '{sport}', 'Sports event'],
                            'xmltv_filler_categories': [],
                            'pregame_periods': [],
                            'pregame_fallback': {'title': 'Coming up: {gracenote_category} at '
                                                          '{game_time.next}',
                                                 'subtitle': '{team1.next} {at_vs.next} '
                                                             '{team2.next}',
                                                 'description': '{game_preview.next}',
                                                 'description_fallback': 'The '
                                                                         '{away_team_record.next} '
                                                                         '{away_team.next} travel '
                                                                         'to {venue_city.next}, '
                                                                         '{venue_state.next} to '
                                                                         'play the '
                                                                         '{home_team_record.next} '
                                                                         '{home_team.next} '
                                                                         '{today_tonight.next} at '
                                                                         '{game_time.next}.',
                                                 'art_url': '{league_id}/{away_team.next|pascal}/{home_team.next|pascal}/cover.png?style=1&logo=true&fallback=true'},
                            'postgame_periods': [],
                            'postgame_fallback': {'title': '{gracenote_category}: Final',
                                                  'subtitle': '{team1.last} {at_vs.last} '
                                                              '{team2.last}',
                                                  'description': '{team_name_the} '
                                                                 '{result_text.last} '
                                                                 '{opponent_the.last} '
                                                                 '{final_score.last}',
                                                  'art_url': '{league_id}/{away_team.last|pascal}/{home_team.last|pascal}/cover.png?style=1&logo=true&fallback=true'},
                            'postgame_conditional': {'enabled': False,
                                                     'description_final': None,
                                                     'description_not_final': None},
                            'postgame_conditional_rows': [{'condition': 'has_recap',
                                                           'condition_value': None,
                                                           'template': '{game_recap.last}',
                                                           'priority': 10,
                                                           'label': 'Recap (provider)'},
                                                          {'condition': 'is_not_final',
                                                           'condition_value': None,
                                                           'template': 'The game between '
                                                                       '{team_name_the} and '
                                                                       '{opponent_the.last} has '
                                                                       'not yet ended as of the '
                                                                       'last update.',
                                                           'priority': 50,
                                                           'label': 'In progress'}],
                            'idle_content': {'title': 'No {team_name} Game Today',
                                             'subtitle': 'Next game: {game_date.next} at '
                                                         '{game_time.next} {vs_at.next} '
                                                         '{opponent_the.next}',
                                             'description': 'Next game: {game_date.next} at '
                                                            '{game_time.next}. The '
                                                            '{away_team_record.next} '
                                                            '{away_team.next} travel to '
                                                            '{venue_city.next}, {venue_state.next} '
                                                            'to play the {home_team_record.next} '
                                                            '{home_team.next} at {venue.next}.',
                                             'art_url': ''},
                            'idle_conditional': {'enabled': False,
                                                 'description_final': None,
                                                 'description_not_final': None},
                            'idle_conditional_rows': [{'condition': 'is_final',
                                                       'condition_value': None,
                                                       'template': '{team_name_the} '
                                                                   '{result_text.last} '
                                                                   '{opponent_the.last} '
                                                                   '{final_score.last} '
                                                                   '{overtime_text.last} on '
                                                                   '{game_date.last}. Next game '
                                                                   'will be with '
                                                                   '{opponent_the.next} on '
                                                                   '{game_date.next} at '
                                                                   '{game_time.next}.',
                                                       'priority': 50,
                                                       'label': 'Final'},
                                                      {'condition': 'is_not_final',
                                                       'condition_value': None,
                                                       'template': '{team_name_the} last played '
                                                                   'against {opponent_the.last} on '
                                                                   '{game_date.last}. Next game '
                                                                   'will be with '
                                                                   '{opponent_the.next} on '
                                                                   '{game_date.next} at '
                                                                   '{game_time.next}.',
                                                       'priority': 50,
                                                       'label': 'In progress'}],
                            'pregame_conditional_rows': [],
                            'idle_offseason': {'title_enabled': False,
                                               'title': None,
                                               'subtitle_enabled': True,
                                               'subtitle': 'No upcoming game currently on schedule '
                                                           'in next 30 days',
                                               'description_enabled': True,
                                               'description': 'No upcoming {team_name} games '
                                                              'scheduled.'},
                            'conditional_descriptions': [{'condition': 'has_preview',
                                                          'condition_value': None,
                                                          'template': '{game_preview}',
                                                          'priority': 10,
                                                          'label': 'Preview (provider)'},
                                                         {'condition': 'has_event_note',
                                                          'condition_value': None,
                                                          'template': '{game_event_note}. '
                                                                      '{away_team_rank_display} '
                                                                      '{away_team} '
                                                                      '({away_team_record}) and '
                                                                      '{home_team_rank_display} '
                                                                      '{home_team} '
                                                                      '({home_team_record}) meet '
                                                                      'at {venue}.',
                                                          'priority': 15,
                                                          'label': 'Marquee note'},
                                                         {'condition': 'is_neutral_site',
                                                          'condition_value': None,
                                                          'template': '{away_team_rank_display} '
                                                                      '{away_team} '
                                                                      '({away_team_record}) and '
                                                                      '{home_team_rank_display} '
                                                                      '{home_team} '
                                                                      '({home_team_record}) meet '
                                                                      'at {venue}. '
                                                                      '{last_five_summary} '
                                                                      '{series_summary}',
                                                          'priority': 17,
                                                          'label': 'Neutral site'},
                                                         {'condition': 'is_conference_game',
                                                          'condition_value': None,
                                                          'template': '{home_team_rank_display} '
                                                                      '{home_team} '
                                                                      '({home_team_record}) host '
                                                                      '{away_team_rank_display} '
                                                                      '{away_team} '
                                                                      '({away_team_record}) in '
                                                                      '{college_conference} play '
                                                                      'at {venue}. '
                                                                      '{last_five_summary} '
                                                                      '{series_summary}',
                                                          'priority': 18,
                                                          'label': 'Conference game'},
                                                         {'condition': 'has_structured_preview',
                                                          'condition_value': None,
                                                          'template': '{home_team_rank_display} '
                                                                      '{home_team} '
                                                                      '({home_team_record}) host '
                                                                      '{away_team_rank_display} '
                                                                      '{away_team} '
                                                                      '({away_team_record}) at '
                                                                      '{venue}. '
                                                                      '{last_five_summary} '
                                                                      '{series_summary}',
                                                          'priority': 20,
                                                          'label': 'Structured preview'},
                                                         {'condition': None,
                                                          'condition_value': None,
                                                          'template': '{home_team_rank_display} '
                                                                      '{home_team} '
                                                                      '({home_team_record}) host '
                                                                      '{away_team_rank_display} '
                                                                      '{away_team} '
                                                                      '({away_team_record}) at '
                                                                      '{venue}.',
                                                          'priority': 100,
                                                          'label': 'Default'}],
                            'event_channel_name': '{team_name}',
                            'event_channel_logo_url': '',
                            'name': 'College Team (Starter)'},
 'Default Event (Starter)': {'template_type': 'event',
                             'title_format': '{gracenote_category}',
                             'subtitle_template': '{team1} {at_vs} {team2}',
                             'program_art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true',
                             'game_duration_mode': 'sport',
                             'pregame_enabled': True,
                             'postgame_enabled': True,
                             'idle_enabled': False,
                             'xmltv_flags': {'new': True, 'live': True, 'date': True},
                             'xmltv_video': {'enabled': False, 'quality': 'HDTV'},
                             'xmltv_categories': ['Sports', '{sport}', 'Sports event'],
                             'xmltv_filler_categories': [],
                             'pregame_periods': [],
                             'pregame_fallback': {'title': 'Coming up: {gracenote_category} at '
                                                           '{game_time}',
                                                  'subtitle': '{team1} {at_vs} {team2}',
                                                  'description': '{game_preview}',
                                                  'description_fallback': 'The {away_team_record} '
                                                                          '{away_team} travel to '
                                                                          '{venue_city}, '
                                                                          '{venue_state} to play '
                                                                          'the {home_team_record} '
                                                                          '{home_team} '
                                                                          '{today_tonight} at '
                                                                          '{game_time}.',
                                                  'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                             'postgame_periods': [],
                             'postgame_fallback': {'title': '{gracenote_category}: Final',
                                                   'subtitle': '{team1} {at_vs} {team2}',
                                                   'description': 'Final: {event_result}',
                                                   'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                             'postgame_conditional': {'enabled': False,
                                                      'description_final': None,
                                                      'description_not_final': None},
                             'postgame_conditional_rows': [{'condition': 'has_recap',
                                                            'condition_value': None,
                                                            'template': '{game_recap}',
                                                            'priority': 10,
                                                            'label': 'Recap (provider)'},
                                                           {'condition': 'is_not_final',
                                                            'condition_value': None,
                                                            'template': 'The game between '
                                                                        '{away_team_the} and '
                                                                        '{home_team_the} has not '
                                                                        'yet ended as of the last '
                                                                        'update.',
                                                            'priority': 50,
                                                            'label': 'In progress'}],
                             'idle_content': {'title': '{league} Programming',
                                              'subtitle': '',
                                              'description': '',
                                              'art_url': ''},
                             'idle_conditional': {'enabled': False,
                                                  'description_final': None,
                                                  'description_not_final': None},
                             'idle_conditional_rows': [],
                             'pregame_conditional_rows': [],
                             'idle_offseason': {'title_enabled': False,
                                                'title': None,
                                                'subtitle_enabled': False,
                                                'subtitle': '',
                                                'description_enabled': False,
                                                'description': ''},
                             'conditional_descriptions': [{'condition': 'has_preview',
                                                           'condition_value': None,
                                                           'template': '{game_preview}',
                                                           'priority': 10,
                                                           'label': 'Preview (provider)'},
                                                          {'condition': 'has_event_note',
                                                           'condition_value': None,
                                                           'template': '{game_event_note}. The '
                                                                       '{away_team_record} '
                                                                       '{away_team} and the '
                                                                       '{home_team_record} '
                                                                       '{home_team} meet at '
                                                                       '{venue}.',
                                                           'priority': 15,
                                                           'label': 'Marquee note'},
                                                          {'condition': 'is_neutral_site',
                                                           'condition_value': None,
                                                           'template': 'The {away_team_record} '
                                                                       '{away_team} and the '
                                                                       '{home_team_record} '
                                                                       '{home_team} meet at '
                                                                       '{venue}. '
                                                                       '{last_five_summary} '
                                                                       '{series_summary}',
                                                           'priority': 17,
                                                           'label': 'Neutral site'},
                                                          {'condition': 'has_structured_preview',
                                                           'condition_value': None,
                                                           'template': 'The {away_team_record} '
                                                                       '{away_team} travel to '
                                                                       '{venue_city}, '
                                                                       '{venue_state} to play the '
                                                                       '{home_team_record} '
                                                                       '{home_team} at {venue}. '
                                                                       '{last_five_summary} '
                                                                       '{series_summary}',
                                                           'priority': 20,
                                                           'label': 'Structured preview'},
                                                          {'condition': None,
                                                           'condition_value': None,
                                                           'template': 'The {away_team_record} '
                                                                       '{away_team} travel to '
                                                                       '{venue_city}, '
                                                                       '{venue_state} to play the '
                                                                       '{home_team_record} '
                                                                       '{home_team} at {venue}.',
                                                           'priority': 100,
                                                           'label': 'Default'}],
                             'event_channel_name': '{league} | {team1_abbrev}/{team2_abbrev}',
                             'event_channel_logo_url': '{league_code}/{away_team|pascal}/{home_team|pascal}/logo.png?style=1&logo=true&fallback=true&badge={broadcast_national_network}%20{exception_keyword}',
                             'name': 'Default Event (Starter)'},
 'College Event (Starter)': {'template_type': 'event',
                             'title_format': '{gracenote_category}',
                             'subtitle_template': '{team1} {at_vs} {team2}',
                             'program_art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true',
                             'game_duration_mode': 'sport',
                             'pregame_enabled': True,
                             'postgame_enabled': True,
                             'idle_enabled': False,
                             'xmltv_flags': {'new': True, 'live': True, 'date': True},
                             'xmltv_video': {'enabled': False, 'quality': 'HDTV'},
                             'xmltv_categories': ['Sports', '{sport}', 'Sports event'],
                             'xmltv_filler_categories': [],
                             'pregame_periods': [],
                             'pregame_fallback': {'title': 'Coming up: {gracenote_category} at '
                                                           '{game_time}',
                                                  'subtitle': '{team1} {at_vs} {team2}',
                                                  'description': '{game_preview}',
                                                  'description_fallback': 'The {away_team_record} '
                                                                          '{away_team} travel to '
                                                                          '{venue_city}, '
                                                                          '{venue_state} to play '
                                                                          'the {home_team_record} '
                                                                          '{home_team} '
                                                                          '{today_tonight} at '
                                                                          '{game_time}.',
                                                  'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                             'postgame_periods': [],
                             'postgame_fallback': {'title': '{gracenote_category}: Final',
                                                   'subtitle': '{team1} {at_vs} {team2}',
                                                   'description': 'Final: {event_result}',
                                                   'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                             'postgame_conditional': {'enabled': False,
                                                      'description_final': None,
                                                      'description_not_final': None},
                             'postgame_conditional_rows': [{'condition': 'has_recap',
                                                            'condition_value': None,
                                                            'template': '{game_recap}',
                                                            'priority': 10,
                                                            'label': 'Recap (provider)'},
                                                           {'condition': 'is_not_final',
                                                            'condition_value': None,
                                                            'template': 'The game between '
                                                                        '{away_team_the} and '
                                                                        '{home_team_the} has not '
                                                                        'yet ended as of the last '
                                                                        'update.',
                                                            'priority': 50,
                                                            'label': 'In progress'}],
                             'idle_content': {'title': '{league} Programming',
                                              'subtitle': '',
                                              'description': '',
                                              'art_url': ''},
                             'idle_conditional': {'enabled': False,
                                                  'description_final': None,
                                                  'description_not_final': None},
                             'idle_conditional_rows': [],
                             'pregame_conditional_rows': [],
                             'idle_offseason': {'title_enabled': False,
                                                'title': None,
                                                'subtitle_enabled': False,
                                                'subtitle': '',
                                                'description_enabled': False,
                                                'description': ''},
                             'conditional_descriptions': [{'condition': 'has_preview',
                                                           'condition_value': None,
                                                           'template': '{game_preview}',
                                                           'priority': 10,
                                                           'label': 'Preview (provider)'},
                                                          {'condition': 'has_event_note',
                                                           'condition_value': None,
                                                           'template': '{game_event_note}. '
                                                                       '{away_team_rank_display} '
                                                                       '{away_team} '
                                                                       '({away_team_record}) and '
                                                                       '{home_team_rank_display} '
                                                                       '{home_team} '
                                                                       '({home_team_record}) meet '
                                                                       'at {venue}.',
                                                           'priority': 15,
                                                           'label': 'Marquee note'},
                                                          {'condition': 'is_neutral_site',
                                                           'condition_value': None,
                                                           'template': '{away_team_rank_display} '
                                                                       '{away_team} '
                                                                       '({away_team_record}) and '
                                                                       '{home_team_rank_display} '
                                                                       '{home_team} '
                                                                       '({home_team_record}) meet '
                                                                       'at {venue}. '
                                                                       '{last_five_summary} '
                                                                       '{series_summary}',
                                                           'priority': 17,
                                                           'label': 'Neutral site'},
                                                          {'condition': 'has_structured_preview',
                                                           'condition_value': None,
                                                           'template': '{home_team_rank_display} '
                                                                       '{home_team} '
                                                                       '({home_team_record}) host '
                                                                       '{away_team_rank_display} '
                                                                       '{away_team} '
                                                                       '({away_team_record}) at '
                                                                       '{venue}. '
                                                                       '{last_five_summary} '
                                                                       '{series_summary}',
                                                           'priority': 20,
                                                           'label': 'Structured preview'},
                                                          {'condition': None,
                                                           'condition_value': None,
                                                           'template': '{home_team_rank_display} '
                                                                       '{home_team} '
                                                                       '({home_team_record}) host '
                                                                       '{away_team_rank_display} '
                                                                       '{away_team} '
                                                                       '({away_team_record}) at '
                                                                       '{venue}.',
                                                           'priority': 100,
                                                           'label': 'Default'}],
                             'event_channel_name': '{league} | {team1_abbrev}/{team2_abbrev}',
                             'event_channel_logo_url': '{league_code}/{away_team|pascal}/{home_team|pascal}/logo.png?style=1&logo=true&fallback=true&badge={broadcast_national_network}%20{exception_keyword}',
                             'name': 'College Event (Starter)'},
 'Soccer Club Event (Starter)': {'template_type': 'event',
                                 'title_format': '{gracenote_category}',
                                 'subtitle_template': '{team1} vs {team2}',
                                 'program_art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true',
                                 'game_duration_mode': 'sport',
                                 'pregame_enabled': True,
                                 'postgame_enabled': True,
                                 'idle_enabled': False,
                                 'xmltv_flags': {'new': True, 'live': True, 'date': True},
                                 'xmltv_video': {'enabled': False, 'quality': 'HDTV'},
                                 'xmltv_categories': ['Sports', '{sport}', 'Sports event'],
                                 'xmltv_filler_categories': [],
                                 'pregame_periods': [],
                                 'pregame_fallback': {'title': 'Coming up: {gracenote_category} at '
                                                               '{game_time}',
                                                      'subtitle': '{away_team} vs {home_team}',
                                                      'description': '{game_preview}',
                                                      'description_fallback': '{away_team_the} '
                                                                              'face '
                                                                              '{home_team_the} at '
                                                                              '{venue} '
                                                                              '{today_tonight} at '
                                                                              '{game_time}.',
                                                      'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                                 'postgame_periods': [],
                                 'postgame_fallback': {'title': '{gracenote_category}: Full Time',
                                                       'subtitle': '{away_team} vs {home_team}',
                                                       'description': 'Full time: {event_result}',
                                                       'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                                 'postgame_conditional': {'enabled': False,
                                                          'description_final': None,
                                                          'description_not_final': None},
                                 'postgame_conditional_rows': [{'condition': 'has_recap',
                                                                'condition_value': None,
                                                                'template': '{game_recap}',
                                                                'priority': 10,
                                                                'label': 'Recap (provider)'},
                                                               {'condition': 'is_not_final',
                                                                'condition_value': None,
                                                                'template': 'The game between '
                                                                            '{away_team_the} and '
                                                                            '{home_team_the} has '
                                                                            'not yet ended as of '
                                                                            'the last update.',
                                                                'priority': 50,
                                                                'label': 'In progress'}],
                                 'idle_content': {'title': '{league} Programming',
                                                  'subtitle': '',
                                                  'description': '',
                                                  'art_url': ''},
                                 'idle_conditional': {'enabled': False,
                                                      'description_final': None,
                                                      'description_not_final': None},
                                 'idle_conditional_rows': [],
                                 'pregame_conditional_rows': [],
                                 'idle_offseason': {'title_enabled': False,
                                                    'title': None,
                                                    'subtitle_enabled': False,
                                                    'subtitle': '',
                                                    'description_enabled': False,
                                                    'description': ''},
                                 'conditional_descriptions': [{'condition': 'has_preview',
                                                               'condition_value': None,
                                                               'template': '{game_preview}',
                                                               'priority': 10,
                                                               'label': 'Preview (provider)'},
                                                              {'condition': 'has_match_note',
                                                               'condition_value': None,
                                                               'template': '{soccer_match_note}. '
                                                                           '{away_team_the} face '
                                                                           '{home_team_the} at '
                                                                           '{venue}.',
                                                               'priority': 15,
                                                               'label': 'Competition note'},
                                                              {'condition': 'has_structured_preview',
                                                               'condition_value': None,
                                                               'template': '{away_team_the} face '
                                                                           '{home_team_the} at '
                                                                           '{venue}. '
                                                                           '{last_five_summary} '
                                                                           '{series_summary}',
                                                               'priority': 20,
                                                               'label': 'Structured preview'},
                                                              {'condition': None,
                                                               'condition_value': None,
                                                               'template': '{away_team_the} face '
                                                                           '{home_team_the} at '
                                                                           '{venue}.',
                                                               'priority': 100,
                                                               'label': 'Default'}],
                                 'event_channel_name': '{league} | {away_team_abbrev} v '
                                                       '{home_team_abbrev}',
                                 'event_channel_logo_url': '{league_code}/{away_team|pascal}/{home_team|pascal}/logo.png?style=1&logo=true&fallback=true&badge={broadcast_national_network}%20{exception_keyword}',
                                 'name': 'Soccer Club Event (Starter)'},
 'Combat Event (Starter)': {'template_type': 'event',
                            'title_format': '{league} {event_number}: {card_segment_display}',
                            'subtitle_template': '{team1} vs {team2}',
                            'program_art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true',
                            'game_duration_mode': 'sport',
                            'pregame_enabled': True,
                            'postgame_enabled': True,
                            'idle_enabled': False,
                            'xmltv_flags': {'new': True, 'live': True, 'date': True},
                            'xmltv_video': {'enabled': False, 'quality': 'HDTV'},
                            'xmltv_categories': ['Sports', '{sport}', 'Sports event'],
                            'xmltv_filler_categories': [],
                            'pregame_periods': [],
                            'pregame_fallback': {'title': 'Coming up: {league} {event_number} at '
                                                          '{game_time}',
                                                 'subtitle': '{away_team} vs {home_team}',
                                                 'description': '{game_preview}',
                                                 'description_fallback': '{away_team} takes on '
                                                                         '{home_team} at {venue} '
                                                                         '{today_tonight} at '
                                                                         '{game_time}.',
                                                 'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                            'postgame_periods': [],
                            'postgame_fallback': {'title': '{league} {event_number}: Event '
                                                           'Complete',
                                                  'subtitle': '{away_team} vs {home_team}',
                                                  'description': '{away_team} vs {home_team} has '
                                                                 'concluded at {venue}.',
                                                  'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                            'postgame_conditional': {'enabled': False,
                                                     'description_final': None,
                                                     'description_not_final': None},
                            'postgame_conditional_rows': [{'condition': 'has_recap',
                                                           'condition_value': None,
                                                           'template': '{game_recap}',
                                                           'priority': 10,
                                                           'label': 'Recap (provider)'},
                                                          {'condition': 'is_not_final',
                                                           'condition_value': None,
                                                           'template': 'The bout between '
                                                                       '{away_team} and '
                                                                       '{home_team} has not yet '
                                                                       'ended as of the last '
                                                                       'update.',
                                                           'priority': 50,
                                                           'label': 'In progress'}],
                            'idle_content': {'title': '{league} Programming',
                                             'subtitle': '',
                                             'description': '',
                                             'art_url': ''},
                            'idle_conditional': {'enabled': False,
                                                 'description_final': None,
                                                 'description_not_final': None},
                            'idle_conditional_rows': [],
                            'pregame_conditional_rows': [],
                            'idle_offseason': {'title_enabled': False,
                                               'title': None,
                                               'subtitle_enabled': False,
                                               'subtitle': '',
                                               'description_enabled': False,
                                               'description': ''},
                            'conditional_descriptions': [{'condition': 'has_preview',
                                                          'condition_value': None,
                                                          'template': '{game_preview}',
                                                          'priority': 10,
                                                          'label': 'Preview (provider)'},
                                                         {'condition': None,
                                                          'condition_value': None,
                                                          'template': '{away_team} takes on '
                                                                      '{home_team} at {venue}.',
                                                          'priority': 100,
                                                          'label': 'Default'}],
                            'event_channel_name': '{league} {event_number} {card_segment_display}',
                            'event_channel_logo_url': '{league_code}/{away_team|pascal}/{home_team|pascal}/logo.png?style=1&logo=true&fallback=true&badge={broadcast_national_network}%20{exception_keyword}',
                            'name': 'Combat Event (Starter)'},
 'International Event (Starter)': {'template_type': 'event',
                                   'title_format': '{gracenote_category} {year}',
                                   'subtitle_template': '{team1} vs {team2}',
                                   'program_art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true',
                                   'game_duration_mode': 'sport',
                                   'pregame_enabled': True,
                                   'postgame_enabled': True,
                                   'idle_enabled': False,
                                   'xmltv_flags': {'new': True, 'live': True, 'date': True},
                                   'xmltv_video': {'enabled': False, 'quality': 'HDTV'},
                                   'xmltv_categories': ['Sports', '{sport}', 'Sports event'],
                                   'xmltv_filler_categories': [],
                                   'pregame_periods': [],
                                   'pregame_fallback': {'title': 'Coming up: {gracenote_category} '
                                                                 'at {game_time}',
                                                        'subtitle': '{team1} {at_vs} {team2}',
                                                        'description': '{game_preview}',
                                                        'description_fallback': 'The '
                                                                                '{away_team_record} '
                                                                                '{away_team} '
                                                                                'travel to '
                                                                                '{venue_city}, '
                                                                                '{venue_state} to '
                                                                                'play the '
                                                                                '{home_team_record} '
                                                                                '{home_team} '
                                                                                '{today_tonight} '
                                                                                'at {game_time}.',
                                                        'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                                   'postgame_periods': [],
                                   'postgame_fallback': {'title': '{gracenote_category}: Full Time',
                                                         'subtitle': '{away_team} vs {home_team}',
                                                         'description': 'Full time: {event_result}',
                                                         'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                                   'postgame_conditional': {'enabled': False,
                                                            'description_final': None,
                                                            'description_not_final': None},
                                   'postgame_conditional_rows': [{'condition': 'has_recap',
                                                                  'condition_value': None,
                                                                  'template': '{game_recap}',
                                                                  'priority': 10,
                                                                  'label': 'Recap (provider)'},
                                                                 {'condition': 'is_not_final',
                                                                  'condition_value': None,
                                                                  'template': 'The game between '
                                                                              '{away_team_the} and '
                                                                              '{home_team_the} has '
                                                                              'not yet ended as of '
                                                                              'the last update.',
                                                                  'priority': 50,
                                                                  'label': 'In progress'}],
                                   'idle_content': {'title': '{league} Programming',
                                                    'subtitle': '',
                                                    'description': '',
                                                    'art_url': ''},
                                   'idle_conditional': {'enabled': False,
                                                        'description_final': None,
                                                        'description_not_final': None},
                                   'idle_conditional_rows': [],
                                   'pregame_conditional_rows': [],
                                   'idle_offseason': {'title_enabled': False,
                                                      'title': None,
                                                      'subtitle_enabled': False,
                                                      'subtitle': '',
                                                      'description_enabled': False,
                                                      'description': ''},
                                   'conditional_descriptions': [{'condition': 'has_preview',
                                                                 'condition_value': None,
                                                                 'template': '{game_preview}',
                                                                 'priority': 10,
                                                                 'label': 'Preview (provider)'},
                                                                {'condition': 'has_match_note',
                                                                 'condition_value': None,
                                                                 'template': '{soccer_match_note}. '
                                                                             '{away_team_the} face '
                                                                             '{home_team_the} at '
                                                                             '{venue}.',
                                                                 'priority': 15,
                                                                 'label': 'Competition note'},
                                                                {'condition': 'has_structured_preview',
                                                                 'condition_value': None,
                                                                 'template': '{away_team_the} face '
                                                                             '{home_team_the} at '
                                                                             '{venue}. '
                                                                             '{last_five_summary} '
                                                                             '{series_summary}',
                                                                 'priority': 20,
                                                                 'label': 'Structured preview'},
                                                                {'condition': None,
                                                                 'condition_value': None,
                                                                 'template': '{away_team_the} face '
                                                                             '{home_team_the} at '
                                                                             '{venue}.',
                                                                 'priority': 100,
                                                                 'label': 'Default'}],
                                   'event_channel_name': '{away_team_abbrev} v {home_team_abbrev}',
                                   'event_channel_logo_url': '{league_code}/{away_team|pascal}/{home_team|pascal}/logo.png?style=1&logo=true&fallback=true&badge={broadcast_national_network}%20{exception_keyword}',
                                   'name': 'International Event (Starter)'},
 'Tennis Event (Starter)': {'template_type': 'event',
                            'title_format': '{year} {tournament_name}',
                            'subtitle_template': '{tennis_round} - {player1} vs {player2}',
                            'program_art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true',
                            'game_duration_mode': 'sport',
                            'pregame_enabled': True,
                            'postgame_enabled': True,
                            'idle_enabled': False,
                            'xmltv_flags': {'new': True, 'live': True, 'date': True},
                            'xmltv_video': {'enabled': False, 'quality': 'HDTV'},
                            'xmltv_categories': ['Sports', '{sport}', 'Sports event'],
                            'xmltv_filler_categories': [],
                            'pregame_periods': [],
                            'pregame_fallback': {'title': 'Coming up: {tournament_name} at '
                                                          '{game_time}',
                                                 'subtitle': '{player1} vs {player2}',
                                                 'description': '{game_preview}',
                                                 'description_fallback': '{player1} takes on '
                                                                         '{player2} in the '
                                                                         '{tennis_round} of '
                                                                         '{tournament_name_the} '
                                                                         '({tennis_draw}).',
                                                 'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                            'postgame_periods': [],
                            'postgame_fallback': {'title': '{tournament_name}: Match Complete',
                                                  'subtitle': '{player1} vs {player2}',
                                                  'description': '{player1} and {player2} have '
                                                                 'completed their {tennis_round} '
                                                                 'match at {tournament_name_the}.',
                                                  'art_url': '{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png?style=6&logo=true&fallback=true'},
                            'postgame_conditional': {'enabled': False,
                                                     'description_final': None,
                                                     'description_not_final': None},
                            'postgame_conditional_rows': [{'condition': 'is_final',
                                                           'condition_value': None,
                                                           'template': '{tennis_result}',
                                                           'priority': 50,
                                                           'label': 'Final'},
                                                          {'condition': 'is_not_final',
                                                           'condition_value': None,
                                                           'template': 'The match between '
                                                                       '{player1} and {player2} '
                                                                       'has not yet ended as of '
                                                                       'the last update.',
                                                           'priority': 50,
                                                           'label': 'In progress'}],
                            'idle_content': {'title': '{league} Programming',
                                             'subtitle': '',
                                             'description': '',
                                             'art_url': ''},
                            'idle_conditional': {'enabled': False,
                                                 'description_final': None,
                                                 'description_not_final': None},
                            'idle_conditional_rows': [],
                            'pregame_conditional_rows': [],
                            'idle_offseason': {'title_enabled': False,
                                               'title': None,
                                               'subtitle_enabled': False,
                                               'subtitle': '',
                                               'description_enabled': False,
                                               'description': ''},
                            'conditional_descriptions': [{'condition': 'has_preview',
                                                          'condition_value': None,
                                                          'template': '{game_preview}',
                                                          'priority': 10,
                                                          'label': 'Preview (provider)'},
                                                         {'condition': None,
                                                          'condition_value': None,
                                                          'template': '{player1} takes on '
                                                                      '{player2} in the '
                                                                      '{tennis_round} of '
                                                                      '{tournament_name_the} '
                                                                      '({tennis_draw}).',
                                                          'priority': 100,
                                                          'label': 'Default'}],
                            'event_channel_name': '{player1_last} v {player2_last}',
                            'event_channel_logo_url': '{league_code}/{away_team|pascal}/{home_team|pascal}/logo.png?style=1&logo=true&fallback=true&badge={broadcast_national_network}%20{exception_keyword}',
                            'name': 'Tennis Event (Starter)'},
 'Racing Event (Starter)': {'template_type': 'event',
                            'title_format': '{gracenote_category}',
                            'subtitle_template': '{race_name}, {session_name}',
                            'program_art_url': '',
                            'game_duration_mode': 'sport',
                            'pregame_enabled': True,
                            'postgame_enabled': True,
                            'idle_enabled': False,
                            'xmltv_flags': {'new': True, 'live': True, 'date': True},
                            'xmltv_video': {'enabled': False, 'quality': 'HDTV'},
                            'xmltv_categories': ['Sports', '{sport}', 'Sports event'],
                            'xmltv_filler_categories': [],
                            'pregame_periods': [],
                            'pregame_fallback': {'title': 'Coming up: {session_name} at '
                                                          '{game_time}',
                                                 'subtitle': '{race_name}, {session_name}',
                                                 'description': '{game_preview}',
                                                 'description_fallback': '{race_name} '
                                                                         '{session_name} from '
                                                                         '{circuit_name} '
                                                                         '{today_tonight} at '
                                                                         '{game_time}.',
                                                 'art_url': ''},
                            'postgame_periods': [],
                            'postgame_fallback': {'title': '{race_name}: {session_name} Complete',
                                                  'subtitle': '{race_name}, {session_name}',
                                                  'description': '{race_name} {session_name} has '
                                                                 'concluded at {circuit_name}.',
                                                  'art_url': ''},
                            'postgame_conditional': {'enabled': False,
                                                     'description_final': None,
                                                     'description_not_final': None},
                            'postgame_conditional_rows': [{'condition': 'has_recap',
                                                           'condition_value': None,
                                                           'template': '{game_recap}',
                                                           'priority': 10,
                                                           'label': 'Recap (provider)'},
                                                          {'condition': 'is_not_final',
                                                           'condition_value': None,
                                                           'template': '{race_name} {session_name} '
                                                                       'has not yet ended as of '
                                                                       'the last update.',
                                                           'priority': 50,
                                                           'label': 'In progress'}],
                            'idle_content': {'title': '{league} Programming',
                                             'subtitle': '',
                                             'description': '',
                                             'art_url': ''},
                            'idle_conditional': {'enabled': False,
                                                 'description_final': None,
                                                 'description_not_final': None},
                            'idle_conditional_rows': [],
                            'pregame_conditional_rows': [],
                            'idle_offseason': {'title_enabled': False,
                                               'title': None,
                                               'subtitle_enabled': False,
                                               'subtitle': '',
                                               'description_enabled': False,
                                               'description': ''},
                            'conditional_descriptions': [{'condition': 'has_preview',
                                                          'condition_value': None,
                                                          'template': '{game_preview}',
                                                          'priority': 10,
                                                          'label': 'Preview (provider)'},
                                                         {'condition': None,
                                                          'condition_value': None,
                                                          'template': '{race_name} {session_name} '
                                                                      'at {circuit_name}.',
                                                          'priority': 100,
                                                          'label': 'Default'}],
                            'event_channel_name': '{league} | {session_name}',
                            'event_channel_logo_url': '',
                            'name': 'Racing Event (Starter)'}}
