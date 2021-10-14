Data Partitioning
=================

When using the Lithop's map function to run a single function over a
rather large file, one might consider breaking the workload to smaller
portions, handing each portion to a separate thread. We refer to said
portions as chunks.

Hereinafter is an example for using a map function to read a csv. file,
stored in COS, split to pre-determined sized chunks:

.. code:: python

    def line_counter_in_chunk(obj):
        counter = {}
        data = obj.data_stream.read()

        for line in data.decode('utf-8').split('\n'):
            if line not in counter:
                counter[line] = 1
            else:
                counter[line] += 1
        return counter


    if __name__ == "__main__":
        data_location = 'cos://bucket_name/file_name.csv'
        size = int(6.7 * pow(2,20))  # ~6.7MiB - arbitrarily chosen chunk size in bytes 

        fexec = lithops.FunctionExecutor()
        fexec.map(line_counter_in_chunk, data_location,obj_chunk_size=size)
        res = fexec.get_result()

        with open('logs/map_output', 'w') as f:
            f.write(str(res).replace('{','\n{'))

-  To take full advantage of the test above (for the next topic), use a
   file with a K number of rows repeating themselves as a routine. You
   may create a csv. example file using the following function:

   .. code:: python

       def create_routine_file():
           """ creates a ~17MB csv. file consisting of 5 lines repeating routine.  """

           # EOL = end of line identifier for ease of testing
           str_routine = """The Project Gutenberg eBook of Judgments in Vacation, by Edward Abbott Parry EOL1
       This eBook is for the use of anyone anywhere in the United States and EOL2  
       most other parts of the world at no cost and with almost no restrictions EOL3
       whatsoever. You may copy it, give it away or re-use it under the terms EOL4
       of the Project Gutenberg License included with this eBook or online at EOL5"""

           ITERATIONS = 45000
           with open('line_integrity.csv', 'a+') as f:
               for i in range(ITERATIONS):
                   f.write(str_routine)
                   if i < ITERATIONS - 1:
                       f.write('\n')

-  Alternatively, One may exchange the obj\_chunk\_size with the
   obj\_chunk\_number parameter to split the file into a known number of
   chunks.

-  You may tinker with the test's parameters, such as: uploading files
   of different size, altering the chunk size, running a map function of
   your choosing, but, As written in the documentation, chunk size must
   be upwards of 1 MIB.

Keeping line integrity in mind
------------------------------

One important feat implemented as a part of the chunking functionality,
is dividing input file into chunks while making sure no chunk contains
partial lines. Thus, running the test above with any (legal)
configuration of parameters, will output a file consisting of entire
rows solely.

In case you opted to adhere to the recommendation above (regarding the
file contents) you may verify line integrity quickly by exchanging the
call to the map function with the following map\_reduce and adding the
map\_function below:

.. code:: python

    def count_total_matching_lines(results):
        final_result = {}
        for count in results:
            for line in count:
                if line not in final_result:
                    final_result[line] = count[line]
                else:
                    final_result[line] += count[line]

        return final_result

    fexec.map_reduce(line_counter_in_chunk, data_location, count_total_matching_lines, obj_chunk_size=size)

The next part covers the main details of the chunking procedure, as it's
implemented in the Lithops project.

The Algorithm behind the scenes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

As map or map\_reduce is being called, a new job is created (in
lithops/job/job.py). The relevant part of the algorithm begins when
create\_partitions(in lithops/job/partitioner.py) is called, and the
job's chunks are associated with byte range. in this stage of the
algorithm each chunk simply gets its fair share + a fixed threshold,
whose purpose will become apparent shortly. Said byte ranges are pickled
and stored in the cloud.

Later on, each thread is aggregating (unpickling) from the cloud
relevant data associated with its own chunk (in run() of
lithops/worker/taskrunner.py), which contains aforementioned byte
ranges. Amongst other aggregated objects, a data\_stream object that
handles the line integrity is initialized and appended. finally,
taskrunner.py passes it all forwards to the map function (the very
reason the function in the example receives a parameter).
| When users wish to read the chunks, they may do so by calling the read
function (the overriding version of lithops/utils.py), which is
implemented in the following way:

#. Store the first byte of the current chunk, unless the chunk in matter
   is the first / only chunk in the mapping job.

#. Read the whole chunk and store it as a string in the variable
   "retval". Sum of bytes stored is regarded as the default
   last\_row\_end\_pos.

#. Since the first byte is as a matter of fact the last byte of the
   former chunk, we inspect whether it's a new line ('') or not. in case
   of the latter, it means that the current chunk started from the midst
   on a line belonging in its entirety to the former chunk. In such
   case, position first\_row\_start\_pos at the beginning of the next
   line.

#. Due to the fact that each chunk received an extra amount of bytes,
   i.e. the threshold previously mentioned (for the very purpose
   mentioned in clause 3), every chunk, apart from the last one, has to
   rid itself from excessive rows, by moving last\_row\_end\_pos to the
   beginning of the next row within the threshold.

#. finally, retval[first\_row\_start\_pos : last\_row\_end\_pos], which
   contains a chunk free from any split lines, is returned.

