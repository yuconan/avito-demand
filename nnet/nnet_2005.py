
# https://www.kaggle.com/darraghdog/mem-check-1002-ftrlrnnverified
# Models Packages
from sklearn import metrics
from sklearn.metrics import mean_squared_error
import time, gc
import pandas as pd
import numpy as np
from sklearn import preprocessing
from nltk.corpus import stopwords
from sklearn.pipeline import FeatureUnion
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from scipy.sparse import hstack, csr_matrix
from sklearn.model_selection import train_test_split
import plotly.offline as plt
from numba import jit
import nltk, re
from nltk.tokenize import ToktokTokenizer
from nltk.stem import PorterStemmer
import multiprocessing as mp
from collections import Counter
from keras.preprocessing.sequence import pad_sequences
import random
from keras.layers import Input, Dropout, Dense, BatchNormalization,     Activation, concatenate, GRU, CuDNNGRU, Embedding, Flatten, Bidirectional,     MaxPooling1D, Conv1D, Add, Reshape, Lambda, PReLU, GaussianDropout, SpatialDropout1D
from keras.models import Model
from keras.callbacks import ModelCheckpoint, Callback, EarlyStopping#, TensorBoard
from keras import backend as K
from keras import optimizers
from keras.layers import GlobalMaxPooling1D
from keras import initializers
from keras.utils import plot_model
from keras.regularizers import l2
from keras.constraints import non_neg

path = "../"

start_time = time.time()

validation = False

print('[{}] Load Train/Test'.format(time.time() - start_time))
traindf = pd.read_csv(path + 'train.csv.zip', index_col = "item_id", parse_dates = ["activation_date"], compression = 'zip')
traindex = traindf.index
testdf = pd.read_csv(path + 'test.csv.zip', index_col = "item_id", parse_dates = ["activation_date"])
testdex = testdf.index
y = traindf.deal_probability.copy()

traindf.drop("deal_probability",axis=1, inplace=True)
print('Train shape: {} Rows, {} Columns'.format(*traindf.shape))
print('Test shape: {} Rows, {} Columns'.format(*testdf.shape))
traindf['activation_date'].value_counts()
traindf.head()

print('[{}] Create Validation Index'.format(time.time() - start_time))
trnidx = (traindf.activation_date<=pd.to_datetime('2017-03-26')).values
validx = (traindf.activation_date>=pd.to_datetime('2017-03-27')).values

print('[{}] Combine Train and Test'.format(time.time() - start_time))
df = pd.concat([traindf,testdf],axis=0)
df['idx'] = range(df.shape[0])
del traindf,testdf
gc.collect()
print('\nAll Data shape: {} Rows, {} Columns'.format(*df.shape))

df.isnull().sum()

print('[{}] Missing values'.format(time.time() - start_time))
for col in ['param_1', 'param_2', 'param_3', 'description', 'price', 'image']:
    df["bin_no_" + col] = (df[col] != df[col]).astype(np.int32)
cols = [c for c in df.columns if 'bin_no_' in c]
df[cols].head()

print('[{}] Feature Engineering Price'.format(time.time() - start_time))
col = "price"
bins_ = 100
for col in ['price', 'item_seq_number']:
    df['emb_' + col] = pd.qcut(df[col], q = bins_, labels = False, duplicates = 'drop')
    df['emb_' + col].fillna(-1,inplace=True)
    df['emb_' + col].value_counts()
    df["cont_log_%s"%(col)] = np.log(df[col]+0.001)
    df["cont_log_%s"%(col)].fillna(-1,inplace=True)
df["image_top_1"].fillna(-1,inplace=True)

print('[{}] Create Time Variables'.format(time.time() - start_time))
df["emb_weekday"] = df['activation_date'].dt.weekday
df["emb_week_of_year"] = df['activation_date'].dt.week
df.drop(["activation_date","image"],axis=1,inplace=True)

print('[{}] Text Features'.format(time.time() - start_time))
df['text_feat'] = df.apply(lambda row: ' '.join([
    str(row['param_1']),
    str(row['param_2']),
    str(row['param_3'])]),axis=1) # Group Param Features
for col in ['title', 'description', 'text_feat']:
    df[col] = df[col].str.lower()
df['description'] = df['title'].fillna('missd') + ' ' + df["parent_category_name"].fillna('') + ' '                     + df["category_name"].fillna('') + ' ' + df['text_feat'].fillna('') +                     ' ' + df['description'].fillna('')

print('[{}] Categoricals with some low counts'.format(time.time() - start_time))
def lowCtCat(col, cutoff = 20):
    dft         = pd.DataFrame(df[col].values, columns = [col])
    gp          = dft[col].value_counts().reset_index().rename(columns = {'index':col, col:col+'_ct'})
    var         = dft[[col]].merge(gp, on = col, how = 'left')[col+'_ct']
    idx         = var>cutoff
    var[idx]    = (df[col].values)[idx]
    var[~idx]    = 'locount'
    var.fillna('missing', inplace = True)
    return var.astype(str).values
for col_, cut_ in [("user_id", 5), ("image_top_1", 30), ("item_seq_number", 100)]:
    df[col_] = lowCtCat(col_, cutoff = cut_)
for col_, cut_ in [('param_'+str(i+1), 20) for i in range(3)]:
    df['cat_' + col_] = lowCtCat(col_, cutoff = cut_)

print('[{}] Encode Variables'.format(time.time() - start_time))
embed_me = ["emb_item_seq_number", "user_id","image_top_1", "region", 'city', "emb_week_of_year", 'emb_price',             "parent_category_name", "category_name", "user_type", "emb_weekday", 'text_feat']             + ['cat_param_'+str(i+1) for i in range(3)]
for col in embed_me:
    print('Label encode %s'%(col))
    lbl = preprocessing.LabelEncoder()
    df[col] = lbl.fit_transform(df[col].astype(str))

print('[{}] Scale Variables'.format(time.time() - start_time))
scl = StandardScaler()
for col in df.columns:
    if 'cont_' in col:
        print('Scale %s'%(col))
        df[col] = scl.fit_transform(df[col].values.reshape(-1, 1)).flatten()

print('[{}] Embedding dimensions'.format(time.time() - start_time))
col_szs = dict((col, df[col].unique().shape[0]) for col in embed_me)
embed_szs = dict((col, int(np.ceil(np.log(col_szs[col])))+1) for col in embed_me)
print(embed_szs)

print('[{}] Encode Sentences'.format(time.time() - start_time))
toktok = ToktokTokenizer()
porter = PorterStemmer()
tokSentMap = {}
def tokSent(sent):
    sent = sent.replace('/', ' ')
    return " ".join(toktok.tokenize(rgx.sub(' ', sent)))

rgx = re.compile('[%s]' % '!"#%&()*,-./:;<=>?@[\\]^_`{|}~\t\n')
df['description']    =[tokSent(x) for x in df['description'].str.lower().tolist()]
df['title']          =[tokSent(x) for x in df['title'].str.lower().tolist()]
print('[{}] Finished Tokenizing text...'.format(time.time() - start_time))

@jit
def myTokenizerFitJit(strls, max_words, filt = True):
    list_=[]
    for sent in strls:
        if filt:
            sent = rgx.sub(' ', sent)
        for s in sent.split(' '):
            if s!= '':
                list_.append(s)
    return Counter(list_).most_common(max_words)

def myTokenizerFit(strls, max_words = 25000):
    mc = myTokenizerFitJit(strls, max_words)
    return dict((i, c+1) for (c, (i, ii)) in enumerate(mc))

@jit
def fit_sequence(str_, tkn_, filt = True):
    labels = []
    for sent in str_:
        if filt:
            sent = rgx.sub(' ', sent)
        tk = []
        for i in sent.split(' '):
            if i in tkn_:
                if i != '':
                    tk.append(tkn_[i])
        labels.append(tk)
    return labels

print('[{}] Finished FITTING TEXT DATA...'.format(time.time() - start_time))
tok_raw_dsc = myTokenizerFit(df['description'].loc[traindex].values, max_words = 60000)
tok_raw_ttl = myTokenizerFit(df['title'].loc[traindex].values, max_words = 15000)
print('[{}] Finished PROCESSING TEXT DATA...'.format(time.time() - start_time))

df["title"]       = fit_sequence(df.title, tok_raw_ttl)
df["description"] = fit_sequence(df.description, tok_raw_dsc)
df["title"]       = [l if len(l)>0 else [0] for l in df["title"]]
gc.collect()

MAX_DSC = max(tok_raw_dsc.values())+1
MAX_TTL = max(tok_raw_ttl.values())+1

bin_cols = [c for c in df.columns if 'bin_no' in c]
cont_cols = [c for c in df.columns if 'cont_' in c]


print(bin_cols)
print(cont_cols)


def get_keras_data(dataset):
    X = {
        'title': pad_sequences(dataset.title,
                              maxlen=max([len(l) for l in dataset.title]))
        ,'description': pad_sequences(dataset.description,
                              maxlen=max([len(l) for l in dataset.description]))
    }
    for col in embed_szs.keys():
        X[col] = dataset[col].values
    X['bin_vars'] = dataset[bin_cols].values
    X['cont_vars'] = dataset[cont_cols].values
    return X

def map_sort(seq1, seq2):
	return sorted(range(len(seq1)), key=lambda x: max(len(seq1[x]),len(seq2[x])))

def reset_data(dt, bsize):
    max_step = dt.shape[0]
    n_batches = int(np.ceil(max_step*1. / float(bsize)))
    batch_steps = np.array(random.sample(range(n_batches), n_batches))
    sorted_ix = np.array(map_sort(dt["title"].tolist(), dt["description"].tolist()))
    dt.reset_index(drop=True, inplace = True)
    return max_step, batch_steps, sorted_ix, dt

def trn_generator(dt, y, bsize):
    while True:
        max_step, batch_steps, sorted_ix, dt = reset_data(dt, bsize)
        for batch in batch_steps:
            from_ = batch*bsize
            to_   = min((batch+1)*bsize, max_step)
            ix_   = sorted_ix[from_:to_]
            Xbatch = dt.iloc[ix_]
            Xbatch = get_keras_data(Xbatch)
            ybatch = dt.target.iloc[ix_]
            yield Xbatch, ybatch

def val_generator(dt, y, bsize):
    while 1:
        max_step, batch_steps, sorted_ix, dt = reset_data(dt, bsize)
        for batch in batch_steps:
            from_ = batch*bsize
            to_   = min((batch+1)*bsize, max_step)
            ix_   = sorted_ix[from_:to_]
            Xbatch = dt.iloc[ix_]
            Xbatch = get_keras_data(Xbatch)
            ybatch = dt.target.iloc[ix_]
            yield Xbatch, ybatch

def tst_generator(dt, bsize):
    while 1:
        for batch in range(int(np.ceil(dt.shape[0]*1./bsize))):
            from_ = batch*bsize
            to_   = min((batch+1)*bsize, dt.shape[0])
            Xbatch = dt.iloc[from_:to_]
            Xbatch = get_keras_data(Xbatch)
            yield Xbatch

get_keras_data(df[:2])


dtrain = df.loc[traindex,:][trnidx].reset_index()
dvalid = df.loc[traindex,:][validx].reset_index()
dtest  = df.loc[testdex,:].reset_index()
dtrain['target'] = y[trnidx].values
dvalid['target'] = y[validx].values


val_sorted_ix = np.array(map_sort(dvalid["title"].tolist(), dvalid["description"].tolist()))
tst_sorted_ix = np.array(map_sort(dtest ["title"].tolist(), dtest ["description"].tolist()))

y_pred_epochs = []

def get_model(emb_size = 32, dr = 0.1, l2_val = 0.0001):

    def root_mean_squared_error(y_true, y_pred):
        return K.sqrt(K.mean(K.square(y_pred - y_true)))


    def mean_error(y_true, y_pred):
        return K.mean(y_true-y_pred)

    ##Inputs
    title = Input(shape=[None], name="title")
    description = Input(shape=[None], name="description")

    # Categorical embeddings
    emb_inputs = dict((col, Input(shape=[1], name = col))  for col in embed_szs.keys())
    emb_model  = dict((col, Embedding(col_szs[col]+1, emb_n, embeddings_regularizer=l2(l2_val))(emb_inputs[col])) for (col, emb_n) in embed_szs.items())
    fe = concatenate([(emb_) for emb_ in emb_model.values()])
    #fe = SpatialDropout1D(dr)(fe)

    # Binary Inputs
    bin_vars = Input(shape= [len(bin_cols)], name = 'bin_vars')
    ## Continuous Inputs
    cont_vars = Input(shape= [len(cont_cols)], name = 'cont_vars')

    #Embeddings layers
    emb_size = 64
    emb_dsc = Embedding(MAX_DSC, emb_size, embeddings_regularizer=l2(l2_val))(description)
    emb_ttl = Embedding(MAX_TTL, emb_size, embeddings_regularizer=l2(l2_val))(title)

    # GRU Layer
    rnn_dsc = (CuDNNGRU(emb_size))(emb_dsc)
    rnn_ttl = (CuDNNGRU(emb_size)) (emb_ttl)

    #main layer
    main_l = concatenate([
        rnn_dsc
        , rnn_ttl
        , Flatten()(fe)
        , bin_vars
#         ,cont_vars
    ])

    main_l = Dense(32, kernel_regularizer=l2(l2_val)) (main_l)
    main_l = PReLU()(main_l)
    #main_l = BatchNormalization()(main_l)
    main_l = Dropout(dr)(main_l)
    main_l = Dense(16, kernel_regularizer=l2(l2_val)) (main_l)
    main_l = PReLU()(main_l)
    #main_l = BatchNormalization()(main_l)
    main_l = Dropout(dr/2)(main_l)

    #output
    output = Dense(1,activation="linear", kernel_regularizer=l2(l2_val)) (main_l)

    #model
    model = Model([title, description] + [inp for inp in emb_inputs.values()] + [bin_vars] + [cont_vars], output)
    optimizer = optimizers.Adam()
    model.compile(loss=root_mean_squared_error,
                  optimizer=optimizer, metrics=['mae'])

    return model

epochs = 8
batchSize = 512
steps = (dtrain.shape[0]/batchSize+1)*epochs
lr_init, lr_fin = 0.0014, 0.00001
lr_decay  = (lr_init - lr_fin)/steps

bags      = 3
y_pred_ls = []
y_sub_ls  = []
for b in range(bags):
    model = get_model(64, .1,.000015)
    K.set_value(model.optimizer.lr, lr_init)
    K.set_value(model.optimizer.decay, lr_decay)
    #model.summary()
    for i in range(epochs):
        batchSize = min(512*(2**i),1024)
        batchSizeTst = 256
        history = model.fit_generator(
                            trn_generator(dtrain, dtrain.target, batchSize)
                            , epochs=i+1
                            , max_queue_size=10
                            , steps_per_epoch = int(np.ceil(dtrain.shape[0]/batchSize))
                            , verbose=1
                            , initial_epoch=i
#                             , validation_data = val_generator(dvalid, dvalid.target, batchSizeTst)
#                             , validation_steps = int(np.ceil(dvalid.shape[0]*.1/batchSizeTst))
                            , use_multiprocessing=False
                            , workers=5
                            )
        y_pred_ls.append(model.predict_generator(
                        tst_generator(dvalid.iloc[val_sorted_ix], batchSizeTst)
                        , steps = int(np.ceil(dvalid.shape[0]*1./batchSizeTst))
                        , max_queue_size=10
                        , verbose=2)[val_sorted_ix.argsort()])
        y_sub_ls.append(model.predict_generator(
                        tst_generator(dtest .iloc[tst_sorted_ix], batchSizeTst)
                        , steps = int(np.ceil(dtest.shape[0]*1./batchSizeTst))
                        , max_queue_size=10
                        , verbose=2)[tst_sorted_ix.argsort()])
        print('RMSE:', np.sqrt(metrics.mean_squared_error(dvalid['target'], y_pred_ls[-1].flatten())))
        if len(y_pred_ls)>1:
            y_pred = sum(y_pred_ls)/len(y_pred_ls)
            print('RMSE bags:', np.sqrt(metrics.mean_squared_error(dvalid['target'], y_pred.flatten())))

for i,preds in enumerate(y_pred_ls):
    print(i//epochs, i%epochs,' RMSE:', np.sqrt(metrics.mean_squared_error(dvalid['target'], preds.flatten())))
#This code grabs all of the continuous epoch combinations and outputs performance of them bagged
    #(to prevent bad epochs from worsening performance)
for i in range(epochs):
    for j in range(i+1,epochs+1):
        y_pred = sum([sum(y_pred_ls[i+epochs*bag:j+epochs*bag])/len(y_pred_ls[i+epochs*bag:j+epochs*bag]) for bag in range(bags)])/bags
        print(i,' to ',j, 'RMSE bags:', np.sqrt(metrics.mean_squared_error(dvalid['target'], y_pred.flatten())))

i=5
j=8
y_sub = sum([sum(y_sub_ls[i+epochs*bag:j+epochs*bag])/len(y_sub_ls[i+epochs*bag:j+epochs*bag]) for bag in range(bags)])/bags
rnnsub = pd.DataFrame(y_sub,columns=["deal_probability"],index=testdex)
rnnsub['deal_probability'] = rnnsub['deal_probability'].clip(0.0, 1.0) # Between 0 and 1
rnnsub.to_csv("../../sub/rnnsub_2005.csv.gz",index=True,header=True, compression = 'gzip')
