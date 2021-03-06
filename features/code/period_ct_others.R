#install.packages("fasttime")
rm(list=ls())
gc();gc();gc()
library(data.table)
library(RcppRoll)
library(fasttime)
library(Hmisc)
library(readr)

path = '~/avito/data/'
#path = '/Users/dhanley2/Documents/avito/data/'

base_secs = (47*24*3600*365)
date2num = function(df, col){
  setkeyv(df, col)
  tmpdf = data.table(from = unique(df[[col]]))
  tmpdf[,to:= as.numeric(fasttime::fastPOSIXct(from)) - base_secs]
  setkeyv(tmpdf, 'from')
  df = df[tmpdf]
  df[[col]] = NULL
  setnames(df, 'to', col)
  return(df)
}

get_same_day_prices = function(fstr, join_cols){
  # Load base file
  df = data.table(read_csv(paste0(path, paste0(fstr, '.csv')), col_types = list('description' = col_skip(), 'user_id' = col_skip())))
  df= date2num(df, 'activation_date')
  df = df[,keepcols,with=F]
  setkeyv(df, c('item_id'))
  gc(); gc()
  gc(); gc()
  
  # Load train periods
  pdf <- data.table(read_csv(paste0(path,  paste0('periods_', fstr, '.csv')), col_types = list('activation_date' = col_skip())))
  pdf = date2num(pdf, 'date_to')
  pdf = date2num(pdf, 'date_from')
  setkeyv(pdf, c('item_id'))
  gc();gc()
  
  # Load active file
  adf = data.table(read_csv(paste0(path, paste0(fstr, '_active.csv')), col_types = list('description' = col_skip(), 'user_id' = col_skip())))
  adf = adf[title %in% df$title]
  adf = date2num(adf, 'activation_date')
  adf = adf[,keepcols,with=F]
  setkeyv(adf, c('item_id'))
  gc(); gc()
  gc(); gc()
  
  # Join periods and active file
  adf = merge(adf, pdf, by = 'item_id', all.x = T, all.y = F)
  rm(pdf)
  gc(); gc()
  
  # Now try and match up for each date
  dts = unique(df$activation_date)
  dtls = list()
  i = 0 
  for (d in dts){
    print(d); i = i + 1
    a = adf[(date_to>=d) & (date_from<=d) & (!is.na(price))]
    setkeyv(a, join_cols)
    # b[title=='LADA Granta, 2017' & city =='Екатеринбург'][order(activation_date)]
    a = a[, .(.N, min(price), max(price), mean(price, na.rm = T) ), by = setdiff(join_cols, 'price') ]
    setkeyv(a, setdiff(join_cols, 'price') )
    setkeyv(df,setdiff(join_cols, 'price'))
    setnames(a,  c(setdiff(join_cols, 'price') , 'other_count', 'other_min_price', 'other_max_price', 'other_mean_price'))
    a[, activation_date:= d]
    a = merge(a, df[, c(setdiff(join_cols, 'price') , "activation_date"), with=F], by = c(setdiff(join_cols, 'price') , "activation_date"), all.x = F, all.y = F)
    dtls[[i]] = a
    rm(a)
    gc(); gc()
  }
  return(rbindlist(dtls))
}

keepcols = c("item_id", 'activation_date', "category_name", "price",  'region', 'city', 'param_1', 'param_2', 'param_3', 'title')
join_cols = c("category_name", "price", "region", "city", "title")
tstmap = get_same_day_prices('test', join_cols)
tstmap = unique(tstmap)
trnmap = get_same_day_prices('train', join_cols)
trnmap = unique(trnmap)
#tstmap[title=='LADA Granta, 2017' & city =='Екатеринбург'][order(activation_date)]

# Join train
trndf = data.table(read_csv(paste0(path, 'train.csv'), col_types = list('description' = col_skip(), 'user_id' = col_skip())))
trndf[, index:= 1:nrow(trndf)]
trndf = date2num(trndf, 'activation_date')
trndf = trndf[,c(keepcols, 'index'),with=F]
trndf = merge(trndf, trnmap, by = c(setdiff(join_cols, 'price'), 'activation_date'), all.x = T, all.y = F)
trndf = trndf[order(index)]
trndf[, other_mean_price_price := other_mean_price/price]
trndf[, other_min_price_comp := as.integer(price>other_min_price)+1]
trndf[, other_max_price_comp := as.integer(price>other_max_price)+1]

# Join test
tstdf = data.table(read_csv(paste0(path, 'test.csv'), col_types = list('description' = col_skip(), 'user_id' = col_skip())))
tstdf[, index:= 1:nrow(tstdf)]
tstdf = date2num(tstdf, 'activation_date')
tstdf = tstdf[,c(keepcols, 'index'),with=F]
tstdf = merge(tstdf, tstmap, by = c(setdiff(join_cols, 'price'), 'activation_date'), all.x = T, all.y = F)
tstdf = tstdf[order(index)]
tstdf[, other_mean_price_price := other_mean_price/price]
tstdf[, other_min_price_comp := as.integer(price>other_min_price)+1]
tstdf[, other_max_price_comp := as.integer(price>other_max_price)+1]



# Make other data table
keepfeats = c('other_count', 'other_mean_price_price', 'other_min_price_comp', 'other_max_price_comp')
outdf = rbind(trndf[,keepfeats, with=F], tstdf[,keepfeats, with=F])
outdf[is.na(outdf)] = 0

idxtrn = 1:nrow(trndf)
idxtst = setdiff(idxtrn, 1:nrow(tstdf))

hist(outdf[idxtrn]$other_max_price_comp)
hist(outdf[idxtst]$other_max_price_comp)

# Write out the files
writeme = function(df, name){
  write.csv(df, 
            gzfile(paste0(path, '../features/', name,'.gz')), 
            row.names = F, quote = F)
}
writeme(outdf, 'period_ct_others_ctyttl')


