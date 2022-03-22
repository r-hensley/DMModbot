import re

def convert_old_db(old_db):
    if "inreportroom" in old_db:
        # Old DB
        new_db = {
            "prefix": old_db["prefix"],
            "settingup": old_db["insetup"],
            "pause": old_db["pause"],
            "guilds": {},
            "reports": {},
        }
        for guild_id_str, guild_config in old_db["guilds"].items():
            guild_id = int(guild_id_str)
            new_db['guilds'][guild_id] = {"channel": int(guild_config['channel'])}
            if guild_id_str in old_db['modrole']:
                new_db['guilds'][guild_id]['mod_role'] = int(old_db['modrole'][guild_id_str])
        return new_db
    else:
        # already new db
        return old_db

def int_keys_to_str_keys(obj):
    if isinstance(obj, dict):
        new_obj = {}
        for k, v in obj.items():
            if isinstance(k, int):
                new_obj[str(k)] = int_keys_to_str_keys(v)
            else:
                new_obj[k] = int_keys_to_str_keys(v)
        return new_obj
    return obj

discord_id = re.compile(r'^[0-9]{17,22}$')
def str_keys_to_int_keys(obj):
    if isinstance(obj, dict):
        new_obj = {}
        for k, v in obj.items():
            if isinstance(k, str) and discord_id.match(k):
                new_obj[int(k)] = str_keys_to_int_keys(v)
            else:
                new_obj[k] = str_keys_to_int_keys(v)
        return new_obj
    return obj

def get_thread_id_to_thread_info(db):
    return dict((thread_info['thread_id'], thread_info) for thread_info in db['reports'].values())