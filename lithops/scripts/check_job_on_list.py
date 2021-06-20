import sys

if __name__ == '__main__':
    workflow = sys.argv[1]  # nightly_build or PR
    #workflow = 'Push or PR git-action'

    path = ".github/workflows/jobs_to_run.txt"
    #path_demo = '/Users/omercohen/dev1/lithops_test/.github/workflows/jobs_to_run.txt'

    with open(path, 'r') as file:
        filedata = file.read()

    if workflow == 'Push or PR git-action':
        print(filedata[filedata.find(':') + 1:filedata.find('nightly_build')].replace('\n', ' '))  # replace is needed because output must be a one liner.
    else:  # workflow == 'Nightly Build'
        print(filedata[filedata.rfind(':') + 1:].replace('\n', ' '))

