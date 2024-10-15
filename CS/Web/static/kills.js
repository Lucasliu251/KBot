//初始化echarts实例在dom
var myChart = echarts.init(document.getElementById('main'));

//监听窗口大小
window.addEventListener('resize', function() {
    myChart.resize();
});


//指定图表的配置项和数据
var dataset = {
    source: []
};
var option = {
    dataset: dataset,
    xAxis: {type: 'category'},
    yAxis: {},
    series: []
};

async function updateDatasetFromJson() {
    // 获取 dirt.json 中的数据
    const response = await fetch('http://47.115.75.168:5000/api/data');
	if (!response.ok) throw new Error('网络响应不正常.');
    const jsonData = await response.json();

    // 初始化数据集
    let dataset = {
        source: [['date']], // 初始化第一列为日期，玩家列会动态添加
        xAxis: { type: 'category' },
        yAxis: {},
        series: []
    };

    // 提取所有的日期和玩家名称
    const dates = Object.keys(jsonData);
    const playerNames = new Set();

    dates.forEach(date => {
        Object.keys(jsonData[date]).forEach(player => {
            playerNames.add(player); // 收集所有玩家的名称
        });
    });

    // 将玩家名称添加到 dataset.source 的第一行
    playerNames.forEach(player => {
        dataset.source[0].push(player);
    });

    // 为每个玩家添加一列到 series 中
    playerNames.forEach(() => {
        dataset.series.push({ type: 'line' });
    });

    // 遍历 jsonData，构建每一天的击杀数
    dates.forEach(date => {
        let newRow = [date]; // 新的一行，第一列是日期

        // 添加每个玩家的击杀数到新的一行中
        playerNames.forEach(player => {
            let kills = jsonData[date][player] ? jsonData[date][player]["新增击杀数"] : 0;
            newRow.push(kills);
        });

        // 将新行添加到 dataset.source 中
        dataset.source.push(newRow);
    });

    console.log("Updated dataset:", dataset);
    // 你可以在这里使用 dataset 来更新图表，例如：
    myChart.setOption({ dataset, xAxis: dataset.xAxis, series: dataset.series });
}


//调取更新函数
updateDatasetFromJson();
// 使用刚指定的配置项和数据显示图表。
myChart.setOption(option);