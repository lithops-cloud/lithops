# Lithops Testing Guidelines

## Verify Installation:
Run ``` lithops test``` to run an extensive inspection, which simulates your lithops installation on a variety of tests.
 - Get all available options by running ```lithops test --help```  
 - Get all available test functions by running ```lithops test -t help``` to get a list of the available tests. 
   <br/> Run all test instances named <test name>, via ```lithops test -t <test name>```.
   <br/> Run a specific test by prefixing the test name in the following way: ```lithops test -t <test group>.<test name>```. 
 - To get all available groups, run ```lithops test -g help```.
    <br/> Run a single group of tests via ```lithops test -g <group name>```.
   
Alternatively you may run "python3 -m lithops.tests.test_main" followed by aforementioned flags.   

## Contribute:

### Add a test to an existing test group: 
Locate the matching test group in lithops/tests (indicated by file name) and add your test function appropriately:
 - Add your test function as a method inside the class inheriting from unittest.testcase. 
 - Use existing util functions from lithops/tests/util_func or add new ones to that package. 
 - A test that's simultaneously testing any two of the following functions: {async, map, map_reduce} 
   will be placed in the proper file by complying with the following hierarchy: map_reduce > map > async.

### Add a new test group: 
Before adding a test function that aims to test an untested feature:  
 - Create a new file in lithops/tests using the template file as your guide:
    - Create a new copy of the template file and name it "test_feature_name", thus automatically creating a new test group named "feature_name". 
    - Figure out which rows are necessary for your new test group, by following documentation 
      beside the rows, then, proceed to un-comment said rows.
      
 - Continue to add the function by adhering to the instructions in the clause above.


### Additional information: 
Whether you're adding a new function, or a new test group you'd be better off knowing the available resources at your disposal:
 - lithops/tests/util_func contains many functions, divided into categories, that you may find helpful.
 - lithops/tests contains a template_file called "test_template" which contains documentation regarding each 
   common resource/import that may interest you.
 - Many examples utilizing said resources may be found across the "test_*" files of lithops/tests.
 - For a variety of evaluation functions ("assert*") belonging to unittest, browse this [documentation page](https://docs.python.org/3.7/library/unittest.html#module-unittest).

   #### <ins>Examples</ins>:
    - Access the functions in your chosen backend storage class via "STORAGE", e.g. ```STORAGE.put_object```.
    - Access your bucket via ```STORAGE_CONFIG['bucket']```.
    - Pass on "CONFIG" to your function executor instance, to allow your test function to work with users that
      </br> provided a path to the config file via a flag, e.g. ```fexec = lithops.FunctionExecutor(config=CONFIG)```. 
      