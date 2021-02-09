import time
import requests

from lithops import multiprocessing as mp


# import multiprocessing as mp


def lithops_asciiart():
    print(requests.get('https://artii.herokuapp.com/make', params={'text': 'Lithops', 'font': 'univers'}).text,
          flush=True)
    time.sleep(1)
    print('Exceptions will show up without the need to call Process.join():', flush=True)
    time.sleep(1)
    foo = bar


if __name__ == '__main__':
    # For using this functionality, a Redis instance is needed. Check the documentation for further instructions
    mp.config.set_parameter(mp.config.STREAM_STDOUT, True)

    # logging.basicConfig(level=logging.DEBUG)
    # logging.getLogger(mp.__name__).setLevel(logging.DEBUG)

    p = mp.Process(target=lithops_asciiart)
    p.start()

    time.sleep(3)

    p.join()
