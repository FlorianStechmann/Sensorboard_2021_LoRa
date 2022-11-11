# script for plotting a bar plot

import matplotlib.pyplot as plt

# set values
faulty_pkt_no = 37
red_pkt_no = 75

x_data = ["w/o redundancy", "w/ redundancy"]
height_data = [faulty_pkt_no, red_pkt_no]

ticks = []
d = 0
for i in range(17):
    ticks.append(d)
    d += 5

fig = plt.figure()
plt.rcParams.update({'font.size': 20})
plt.rcParams["font.family"] = "Times New Roman"
fig.set_dpi(300.0)

plt.bar(x_data, height_data, zorder=3)
plt.ylim([0, 80])
plt.yticks(ticks)
plt.grid(axis="y")
plt.ylabel("Number of packets transmitted", fontsize=20)
plt.xlabel("Version", fontsize=20)
plt.show()