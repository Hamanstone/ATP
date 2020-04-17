def info_filter(src_string):
    start = "#INFO#"
    end = "#END#\r\n"
    subtract_prefix = (src_string.split(start))[1]
    subtract_postfix = subtract_prefix.split(end)[0]
    if ':' in subtract_postfix:
        execution_result = subtract_postfix.split(':')[0]
        info_string = subtract_postfix.split(':')[1]
        if execution_result == '0':
            return info_string
        else:
            return 0
    else:
        return subtract_postfix


def search_log(hugedata, searchfor):
    ignoreDict = ['\r\n', '/ # \r\n']
    for key in hugedata.keys():
        try:
            if searchfor == hugedata[key] and searchfor not in ignoreDict:
                # update_info_reg(key, "BOOTING")
                return key
        except Exception:
            pass
    return repr(searchfor)


