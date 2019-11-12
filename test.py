# -*- coding:utf-8 -*-
import datetime
import numpy as np
from models.multiscale_multitask_STResNet import stresnet
from models.LSTM import LSTM_Net
import config
import warnings

warnings.filterwarnings("ignore")
START_HOUR = 0  # 凌晨 [0,1,...,23]外部信息
START_MINUTE = 0  # 第一个分钟片 [0,1,2,3,4,5]外部信息

N_days = config.N_days  # 用了多少天的数据(目前17个工作日)
N_hours = config.N_hours
N_time_slice = config.N_time_slice  # 1小时有6个时间片
N_station = config.N_station  # 81个站点
N_flow = config.N_flow  # 进站 & 出站
len_seq1 = config.len_seq1  # week时间序列长度为2
len_seq2 = config.len_seq2  # day时间序列长度为3
len_seq3 = config.len_seq3  # hour时间序列长度为5
nb_flow = config.nb_flow  # 输入特征


def getTemporalInterval(timestamp):
    timestamp = timestamp.replace('/', '-')
    t = datetime.datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
    weekday = t.weekday()
    hour = t.hour
    minute = t.minute
    if 10 > minute >= 0:
        segment = 0
    elif 20 > minute >= 10:
        segment = 1
    elif 30 > minute >= 20:
        segment = 2
    elif 40 > minute >= 30:
        segment = 3
    elif 50 > minute >= 40:
        segment = 4
    else:
        segment = 5
    return weekday, hour, segment


# datetime, stations, status = [],[],[]
def getMetroFlow(datetime, stations, status):
    # 地铁流量矩阵（24*6, 81, 2）
    metro_flow_matrix = np.zeros((N_hours * N_time_slice, N_station, N_flow))
    for i in range(len(datetime)):
        w, h, s = getTemporalInterval(datetime[i])
        station_id = stations[i]
        state = status[i]
        idx = h * 6 + s
        metro_flow_matrix[idx, station_id, state] += 1
    # /100 近似归一化
    metro_flow_matrix /= 100
    return metro_flow_matrix


def mae_compute(truth, predict):
    # 后处理计算
    truth = truth * 100
    truth = np.around(truth, 0)

    # eval_01_25.py生成的文件，替换这里的文件名字，这方面可以再想一想后处理算法来提升精度
    predict = predict * 2945
    predict = np.around(predict, 0)
    # predict[(predict < 10) & (predict > 0)] =2
    predict[predict < 3] = 0  # 玄学2

    # 看第一个loss(mae)
    loss_matrix = np.abs(truth - predict)
    mae = loss_matrix.sum() / (truth.shape[0] * truth.shape[1] * truth.shape[2])

    # 看第二个loss(mape)
    # truth[np.where(truth == 0)] = 0.0001
    loss_matrix2 = np.clip(loss_matrix, 0.001, 3000) / np.clip(truth, 0.001, 3000)
    mape = loss_matrix2.sum() / (truth.shape[0] * truth.shape[1] * truth.shape[2])

    # loss_matrix1 = np.abs(truth - predict1)
    # loss1 = loss_matrix1.sum()/(144*81*2)
    # loss_matrix2 = np.abs(truth - predict2)
    # loss2 = loss_matrix2.sum()/(144*81*2)
    mdae = np.median(np.abs(truth - predict))
    print(mae, mape, mdae)
    return mae, mape


def test_stresnet(data_week, data_day, data_recent, data_week_edge, data_day_edge, data_recent_edge, predict_day,
                  truth_day):
    # ——————————————————————————————组织数据———————————————————————————————
    # 由于>25的数量极其少，将>25的值全都默认为25
    # sub_Metro_Flow2[np.where(sub_Metro_Flow2 > 25)] = 25
    out_maximum = 30  # 估摸出站的最大阈值  因为在getMetroFlow函数中已经除了100近似归一化了
    data_week /= out_maximum
    data_day /= out_maximum
    edge_out_maximum = 233.0
    data_week_edge /= edge_out_maximum
    data_day_edge /= edge_out_maximum

    # ——————————————————————建立模型———————————————————————————
    model = stresnet(c_conf=(len_seq3, N_flow, N_station), p_conf=(len_seq2, N_flow, N_station),
                     t_conf=(len_seq1, N_flow, N_station),
                     c1_conf=(len_seq3, N_station, N_station), p1_conf=(len_seq2, N_station, N_station),
                     t1_conf=(len_seq1, N_station, N_station),
                     external_dim1=1, external_dim2=1, external_dim3=None,
                     external_dim4=1, external_dim5=81, external_dim6=None,
                     external_dim7=None, external_dim8=None, external_dim9=1,
                     nb_residual_unit=4, nb_edge_residual_unit=4)  # 对应修改这里,和训练阶段保持一致
    # model.load_weights('log/edge_conv1d/units_12_3channel_external/05-0.00730342.hdf5')  # 替换这里哦，记住记住！
    model.load_weights(config.model_weights_stresnet)

    xr_test = np.zeros([1, N_station, len_seq3 * N_flow])
    xp_test = np.zeros([1, N_station, len_seq2 * N_flow])
    xt_test = np.zeros([1, N_station, len_seq1 * N_flow])

    xredge_test = np.zeros([1, N_station, len_seq3 * N_station])
    xpedge_test = np.zeros([1, N_station, len_seq2 * N_station])
    xtedge_test = np.zeros([1, N_station, len_seq1 * N_station])
    # 0125是周五,weekday信息
    x_val_external_information1 = np.zeros([24 * 6, 1])
    x_val_external_information1[:, 0] = 4
    # 时间片信息
    x_val_external_information2 = np.zeros([24 * 6, 1])
    HOUR = 0
    for i in range(0, 24 * 6):
        x_val_external_information2[i, 0] = HOUR
        HOUR = HOUR + 1
    # 天气信息,25号为多云
    x_val_external_information4 = np.zeros([24 * 6, 1])
    x_val_external_information4[:, 0] = 1
    # 闸机信息
    x_val_external_information5 = np.zeros([24 * 6, 81])
    t = np.load('./npy/train_data/Two_more_features.npy')
    t = t[:, 0]
    for i in range(144):
        x_val_external_information5[i, :] = t
    # 早晚高峰、高峰、平峰信息
    x_val_external_information9 = np.zeros([N_hours * N_time_slice, 1])
    # #——————————————————早晚高峰—————————————————————
    x_val_external_information9[39:54, 0] = 2  # 7：30 - 9：00
    x_val_external_information9[102:114, 0] = 2  # 17：00 - 19：00
    # #——————————————————高峰—————————————————————————
    x_val_external_information9[33:39, 0] = 1  # 6:30-7:30
    x_val_external_information9[63:70, 0] = 1  # 10:30-11:30
    x_val_external_information9[99:102, 0] = 1  # 16:30-17:30
    x_val_external_information9[114:132, 0] = 1  # 19:00-22:00

    sum_of_predictions = 24 * 6 - config.len_seq3
    for i in range(sum_of_predictions):
        # if i + 4 + config.len_seq1 >= len(data_week) or i + 3 + config.len_seq2 >= len(
        #         data_day) or i + config.len_seq3 >= len(data_recent):
        #     break
        t = data_week[
            i + config.len_seq3 - config.len_seq1 + 1:i + config.len_seq3 - config.len_seq1 + 1 + config.len_seq1, :,
            :]  # trend
        p = data_day[
            i + config.len_seq3 - config.len_seq2 + 1:i + config.len_seq3 - config.len_seq2 + 1 + config.len_seq2, :,
            :]  # period
        r = data_recent[i:i + config.len_seq3, :, :]  # recent
        et = data_week_edge[
             i + config.len_seq3 - config.len_seq1 + 1:i + config.len_seq3 - config.len_seq1 + 1 + config.len_seq1, :,
             :]
        ep = data_day_edge[
             i + config.len_seq3 - config.len_seq2 + 1:i + config.len_seq3 - config.len_seq2 + 1 + config.len_seq2, :,
             :]
        er = data_recent_edge[i:i + config.len_seq3, :, :]
        mask = np.ones([1, 81, 81])
        for j in range(len_seq3):
            for k in range(2):
                xr_test[0, :, j * 2 + k] = r[j, :, k]
        for j in range(len_seq2):
            for k in range(2):
                xp_test[0, :, j * 2 + k] = p[j, :, k]
        for j in range(len_seq1):
            for k in range(2):
                xt_test[0, :, j * 2 + k] = t[j, :, k]

        for j in range(len_seq3):
            for k in range(81):
                xredge_test[0, :, j * 81 + k] = er[j, :, k]
        for j in range(len_seq2):
            for k in range(81):
                xpedge_test[0, :, j * 81 + k] = ep[j, :, k]
        for j in range(len_seq1):
            for k in range(81):
                xtedge_test[0, :, j * 81 + k] = et[j, :, k]
        # 对应修改了这里
        ans, ans1 = model.predict([xr_test, xp_test, xt_test, xredge_test, xpedge_test, xtedge_test, mask,
                                   x_val_external_information1, x_val_external_information2,
                                   x_val_external_information4,
                                   x_val_external_information5, x_val_external_information9])
        data_recent[i + config.len_seq3, :, :] = ans
    np.save(predict_day, data_recent)

    truth = np.load(truth_day)
    predict = np.load(predict_day)
    mae_compute(truth, predict)

    print('Testing Done...')


def test_LSTM(data_week, data_day, data_recent, data_week_edge, data_day_edge, data_recent_edge, predict_day,
              truth_day):
    # ——————————————————————————————组织数据———————————————————————————————
    # 由于>25的数量极其少，将>25的值全都默认为25
    # sub_Metro_Flow2[np.where(sub_Metro_Flow2 > 25)] = 25
    out_maximum = 30  # 估摸出站的最大阈值  因为在getMetroFlow函数中已经除了100近似归一化了
    data_week /= out_maximum
    data_day /= out_maximum
    edge_out_maximum = 233.0
    data_week_edge /= edge_out_maximum
    data_day_edge /= edge_out_maximum

    # ——————————————————————建立模型———————————————————————————
    model = LSTM_Net(c_conf=(len_seq3, N_flow, N_station), p_conf=(len_seq2, N_flow, N_station),
                     t_conf=(len_seq1, N_flow, N_station),
                     c1_conf=(len_seq3, N_station, N_station), p1_conf=(len_seq2, N_station, N_station),
                     t1_conf=(len_seq1, N_station, N_station),
                     external_dim1=1, external_dim2=1, external_dim3=None,
                     external_dim4=1, external_dim5=81, external_dim6=None,
                     external_dim7=None, external_dim8=None, external_dim9=1,
                     nb_residual_unit=12, nb_edge_residual_unit=12)  # 对应修改这里,和训练阶段保持一致
    # model.load_weights('log/edge_conv1d/units_12_3channel_external/05-0.00730342.hdf5')  # 替换这里哦，记住记住！
    model.load_weights(config.model_weights_LSTM)

    xr_test = np.zeros([1, N_station, len_seq3 * N_flow])
    xp_test = np.zeros([1, N_station, len_seq2 * N_flow])
    xt_test = np.zeros([1, N_station, len_seq1 * N_flow])

    xredge_test = np.zeros([1, N_station, len_seq3 * N_station])
    xpedge_test = np.zeros([1, N_station, len_seq2 * N_station])
    xtedge_test = np.zeros([1, N_station, len_seq1 * N_station])
    # 0125是周五,weekday信息
    x_val_external_information1 = np.zeros([24 * 6, 1])
    x_val_external_information1[:, 0] = 4
    # 时间片信息
    x_val_external_information2 = np.zeros([24 * 6, 1])
    HOUR = 0
    for i in range(0, 24 * 6):
        x_val_external_information2[i, 0] = HOUR
        HOUR = HOUR + 1
    # 天气信息,25号为多云
    x_val_external_information4 = np.zeros([24 * 6, 1])
    x_val_external_information4[:, 0] = 1
    # 闸机信息
    x_val_external_information5 = np.zeros([24 * 6, 81])
    t = np.load('./npy/train_data/Two_more_features.npy')
    t = t[:, 0]
    for i in range(144):
        x_val_external_information5[i, :] = t
    # 早晚高峰、高峰、平峰信息
    x_val_external_information9 = np.zeros([N_hours * N_time_slice, 1])
    # #——————————————————早晚高峰—————————————————————
    x_val_external_information9[39:54, 0] = 2  # 7：30 - 9：00
    x_val_external_information9[102:114, 0] = 2  # 17：00 - 19：00
    # #——————————————————高峰—————————————————————————
    x_val_external_information9[33:39, 0] = 1  # 6:30-7:30
    x_val_external_information9[63:70, 0] = 1  # 10:30-11:30
    x_val_external_information9[99:102, 0] = 1  # 16:30-17:30
    x_val_external_information9[114:132, 0] = 1  # 19:00-22:00

    sum_of_predictions = 24 * 6 - config.len_seq3
    for i in range(sum_of_predictions):
        # if i + 4 + config.len_seq1 >= len(data_week) or i + 3 + config.len_seq2 >= len(
        #         data_day) or i + config.len_seq3 >= len(data_recent):
        #     break
        t = data_week[
            i + config.len_seq3 - config.len_seq1 + 1:i + config.len_seq3 - config.len_seq1 + 1 + config.len_seq1, :,
            :]  # trend
        p = data_day[
            i + config.len_seq3 - config.len_seq2 + 1:i + config.len_seq3 - config.len_seq2 + 1 + config.len_seq2, :,
            :]  # period
        r = data_recent[i:i + config.len_seq3, :, :]  # recent
        et = data_week_edge[
             i + config.len_seq3 - config.len_seq1 + 1:i + config.len_seq3 - config.len_seq1 + 1 + config.len_seq1, :,
             :]
        ep = data_day_edge[
             i + config.len_seq3 - config.len_seq2 + 1:i + config.len_seq3 - config.len_seq2 + 1 + config.len_seq2, :,
             :]
        er = data_recent_edge[i:i + config.len_seq3, :, :]
        mask = np.ones([1, 81, 81])
        for j in range(len_seq3):
            for k in range(2):
                xr_test[0, :, j * 2 + k] = r[j, :, k]
        for j in range(len_seq2):
            for k in range(2):
                xp_test[0, :, j * 2 + k] = p[j, :, k]
        for j in range(len_seq1):
            for k in range(2):
                xt_test[0, :, j * 2 + k] = t[j, :, k]

        for j in range(len_seq3):
            for k in range(81):
                xredge_test[0, :, j * 81 + k] = er[j, :, k]
        for j in range(len_seq2):
            for k in range(81):
                xpedge_test[0, :, j * 81 + k] = ep[j, :, k]
        for j in range(len_seq1):
            for k in range(81):
                xtedge_test[0, :, j * 81 + k] = et[j, :, k]
        # 对应修改了这里
        ans, ans1 = model.predict([xr_test, xp_test, xt_test, xredge_test, xpedge_test, xtedge_test, mask,
                                   x_val_external_information1, x_val_external_information2,
                                   x_val_external_information4,
                                   x_val_external_information5, x_val_external_information9])
        data_recent[i + config.len_seq3, :, :] = ans
    np.save(predict_day, data_recent)

    truth = np.load(truth_day)
    predict = np.load(predict_day)
    mae_compute(truth, predict)

    print('Testing Done...')


if __name__ == '__main__':
    # truth = np.load('D:/ADST/npy/mae_compare/truth_day12.npy')
    # predict = np.load('D:/ADST/log/stresnet/3_3_5/predict_day_25.npy')
    # mae_compute(truth, predict)
    # -------------------------------------- test_stresnet-28day-start -------------------------------------- #
    # node_data
    print('test_stresnet-28day-start')
    data_day = np.load('./npy/test_data/raw_node_data_day25.npy')
    data_week = np.load('./npy/test_data/raw_node_data_day21.npy')
    data_recent = np.zeros([N_hours * N_time_slice, N_station, N_flow])

    # edge_data
    data_day_edge = np.load('./npy/test_data/raw_edge_data_day25.npy')
    data_week_edge = np.load('./npy/test_data/raw_edge_data_day21.npy')
    data_recent_edge = np.zeros([N_hours * N_time_slice, N_station, N_station])

    # 预测文件
    predict_day = './npy/mae_compare/predict_day28.npy'

    # 真实文件
    truth_day = './npy/mae_compare/truth_day28.npy'
    test_stresnet(data_week, data_day, data_recent, data_week_edge, data_day_edge, data_recent_edge, predict_day,
                  truth_day)

    # -------------------------------------- test_stresnet-28day-end -------------------------------------- #

    # -------------------------------------- test_stresnet-25day-start -------------------------------------- #
    # node_data
    print('test_stresnet-25day-start')
    data_day = np.load('./npy/test_data/raw_node_data_day24.npy')
    data_week = np.load('./npy/test_data/raw_node_data_day18.npy')
    data_recent = np.zeros([N_hours * N_time_slice, N_station, N_flow])

    # edge_data
    data_day_edge = np.load('./npy/test_data/raw_edge_data_day24.npy')
    data_week_edge = np.load('./npy/test_data/raw_edge_data_day18.npy')
    data_recent_edge = np.zeros([N_hours * N_time_slice, N_station, N_station])

    # 预测文件
    predict_day = './npy/mae_compare/predict_day25.npy'

    # 真实文件
    truth_day = './npy/mae_compare/truth_day25.npy'
    test_stresnet(data_week, data_day, data_recent, data_week_edge, data_day_edge, data_recent_edge, predict_day,
                  truth_day)

    # -------------------------------------- test_stresnet-25day-end -------------------------------------- #

    # -------------------------------------- test_stresnet-20day-start -------------------------------------- #
    # node_data
    print('test_stresnet-20day-start')
    data_day = np.load('./npy/test_data/raw_node_data_day19.npy')
    data_week = np.load('./npy/test_data/raw_node_data_day13.npy')
    data_recent = np.zeros([N_hours * N_time_slice, N_station, N_flow])

    # edge_data
    data_day_edge = np.load('./npy/test_data/raw_edge_data_day19.npy')
    data_week_edge = np.load('./npy/test_data/raw_edge_data_day13.npy')
    data_recent_edge = np.zeros([N_hours * N_time_slice, N_station, N_station])

    # 预测文件
    predict_day = './npy/mae_compare/predict_day20.npy'

    # 真实文件
    truth_day = './npy/mae_compare/truth_day20.npy'
    test_stresnet(data_week, data_day, data_recent, data_week_edge, data_day_edge, data_recent_edge, predict_day,
                  truth_day)
    # -------------------------------------- test_stresnet-20day-end -------------------------------------- #

    # -------------------------------------- test_stresnet-19day-start -------------------------------------- #
    # node_data
    print('test_stresnet-19day-start')
    data_day = np.load('./npy/test_data/raw_node_data_day18.npy')
    data_week = np.load('./npy/test_data/raw_node_data_day12.npy')
    data_recent = np.zeros([N_hours * N_time_slice, N_station, N_flow])

    # edge_data
    data_day_edge = np.load('./npy/test_data/raw_edge_data_day18.npy')
    data_week_edge = np.load('./npy/test_data/raw_edge_data_day12.npy')
    data_recent_edge = np.zeros([N_hours * N_time_slice, N_station, N_station])

    # 预测文件
    predict_day = './npy/mae_compare/predict_day19.npy'

    # 真实文件
    truth_day = './npy/mae_compare/truth_day19.npy'
    test_stresnet(data_week, data_day, data_recent, data_week_edge, data_day_edge, data_recent_edge, predict_day,
                  truth_day)

    # -------------------------------------- test_stresnet-19day-end -------------------------------------- #

    # -------------------------------------- test_stresnet-13day-start -------------------------------------- #
    # node_data
    print('test_stresnet-13day-start')
    data_day = np.load('./npy/test_data/raw_node_data_day12.npy')
    data_week = np.load('./npy/test_data/raw_node_data_day6.npy')
    data_recent = np.zeros([N_hours * N_time_slice, N_station, N_flow])

    # edge_data
    data_day_edge = np.load('./npy/test_data/raw_edge_data_day12.npy')
    data_week_edge = np.load('./npy/test_data/raw_edge_data_day6.npy')
    data_recent_edge = np.zeros([N_hours * N_time_slice, N_station, N_station])

    # 预测文件
    predict_day = './npy/mae_compare/predict_day13.npy'

    # 真实文件
    truth_day = './npy/mae_compare/truth_day13.npy'
    test_stresnet(data_week, data_day, data_recent, data_week_edge, data_day_edge, data_recent_edge, predict_day,
                  truth_day)

    # -------------------------------------- test_stresnet-13day-end -------------------------------------- #

    # -------------------------------------- test_stresnet-12day-start -------------------------------------- #
    # node_data
    print('test_stresnet-12day-start')
    data_day = np.load('./npy/test_data/raw_node_data_day11.npy')
    data_week = np.load('./npy/test_data/raw_node_data_day5.npy')
    data_recent = np.zeros([N_hours * N_time_slice, N_station, N_flow])

    # edge_data
    data_day_edge = np.load('./npy/test_data/raw_edge_data_day11.npy')
    data_week_edge = np.load('./npy/test_data/raw_edge_data_day5.npy')
    data_recent_edge = np.zeros([N_hours * N_time_slice, N_station, N_station])

    # 预测文件
    predict_day = './npy/mae_compare/predict_day12.npy'

    # 真实文件
    truth_day = './npy/mae_compare/truth_day12.npy'
    test_stresnet(data_week, data_day, data_recent, data_week_edge, data_day_edge, data_recent_edge, predict_day,
                  truth_day)

    # -------------------------------------- test_stresnet-12day-end -------------------------------------- #

    # -------------------------------------- test_Arima-25day-start -------------------------------------- #
    print('test_Arima-25day-start')
    predict_day = './npy/mae_compare/predict_arima_day25.npy'
    truth_day = './npy/mae_compare/truth_day25.npy'
    truth = np.load(truth_day)
    predict = np.load(predict_day)
    # truth = truth[0:5, :, :]
    # predict = predict[0:5, :, :]
    mae_compute(truth, predict)
    print('Testing Done...')
    # -------------------------------------- test_Arima-25day-end -------------------------------------- #
    # -------------------------------------- test_predict_stnn-25day-start -------------------------------------- #
    print('test_predict_stnn-25day-start')
    predict_day = './npy/mae_compare/predict_stnn.npy'
    truth_day = './npy/mae_compare/truth_day25.npy'
    truth = np.load(truth_day)
    predict = np.load(predict_day)
    # truth = truth[0:5, :, :]
    # predict = predict[0:5, :, :]
    mae_compute(truth, predict)
    print('Testing Done...')
    # -------------------------------------- test_predict_stnn-25day-end -------------------------------------- #

    # -------------------------------------- test_LSTM-25day-start -------------------------------------- #
    # node_data
    print('test_LSTM-25day-start')
    data_day = np.load('./npy/test_data/raw_node_data_day24.npy')
    data_week = np.load('./npy/test_data/raw_node_data_day18.npy')
    data_recent = np.zeros([N_hours * N_time_slice, N_station, N_flow])

    # edge_data
    data_day_edge = np.load('./npy/test_data/raw_edge_data_day24.npy')
    data_week_edge = np.load('./npy/test_data/raw_edge_data_day18.npy')
    data_recent_edge = np.zeros([N_hours * N_time_slice, N_station, N_station])

    # 预测文件
    predict_day = './npy/mae_compare/predict_day25.npy'

    # 真实文件
    truth_day = './npy/mae_compare/truth_day25.npy'
    test_LSTM(data_week, data_day, data_recent, data_week_edge, data_day_edge, data_recent_edge, predict_day,
              truth_day)
    # -------------------------------------- test_LSTM-25day-end--------------------------------------#
