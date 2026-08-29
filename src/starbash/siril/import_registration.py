# fixme ai heres some samplecode on how to parse .seq files use it as a ReferenceError
# but for this function i want you to return a list of dataclasses with reasonable field names

def parse_siril_seq(file_path):
    data = []
    with open(file_path) as f:
        for line in f:
            if line.startswith('R0 '):
                parts = line.split()
                data.append({
                    'FWHM': float(parts[1]),
                    'Amplitude': float(parts[2]),
                    'Roundness': float(parts[3]),
                    'Background': float(parts[5]),
                    'Stars': int(parts[6])
                })

