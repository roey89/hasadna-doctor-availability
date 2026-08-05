# Available doctor appointments visualization
This is a software tool which does the following:
1. Crawls and fetches data about availability of doctors appointments in several Kupot Holim
2. Extracts the data based on geography and field of experties
3. Merges the data from the different Kupot Holim
4. Visualizes the data on a map

## How To Run
TODO

## The Codebase
The Codebase contains seperate crawlers for each Kupat Holim and the Visualization tool

The Clalit crawler is documented in [Clalit_README.md]

The Maccabi crawler is documented in [Maccabi_README.md] (TODO)

The Visualization tool is documented in [visualization_README.md] (TODO)

## FUTURE WORK
Currently, this tool is a POC on very real data, but not a fully working application.

Also, the paths where the raw data is writted may be different than where the app and the code that tidies it expect it to be, we didn't have time to run everything end to end.

Future work:

1. Add the other Kupot Holim (Meuhedet, Leumit)
2. Debug, Fine-tune and improve the crawling of Clalit and Maccabi
    1. In Maccabi - the crawling didn't succeed to query for family doctors (since there were too much)
    2. In clalit - since the querying was too slow - only several fields were queried. We found that there is 97% shrinkage of the dataframe after we clean and dedup the data, so a massive improvement can be done for certain
    3. Both of them need to be researched for duplicates, misfits between them and other data errors. We did find some standartization that was done by the Misistry of Health, but it wasn't always followed by the Kupah, Examples:
        1. Tel-Aviv vs Tel-Aviv-Yafo vs Tel Aviv
        2. א.א.ג vs אף אוזן גרון
        3. נשים vs גניקולוגיה
3. Add more statistics and filters
    1. Normalize per city-capita. This is *very* important since now the app is very biased towards highly populated cities.
    2. Create a more complex metrics that match desireable behavior and does not encourage hiding data from clients. For example look at K-closest appointments rather than just one (which is the current status), and reward appointments that occur at a closer date.
    3. Look at trends over time, and average over longer time prediods. This will allow insights are more useful and are not influenced by timing.
    4. Add more advanced time and location filters (based on proximity and not cities for example)
4. Make the Crawling run periodically and update a database
   1. Make Clalit not require login
   2. Ideally - run this via a ministry superuser to have access to all the data (also hidden appointments). If there is a way to do the analysis we did on booked appointments (without any patient data of course) in addition to available ones - it will probably resemble the patient's story more accurately.
5. Debug and improve the visualization
6. Tidy and document the code
