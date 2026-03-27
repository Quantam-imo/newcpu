from astroquant.engine.astro_signal import get_astro_signal

def run_astro():
    signal = get_astro_signal()
    return {
        "astro_signal": signal
    }
