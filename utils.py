import math

from datasets import load_dataset, concatenate_datasets
from torch.optim import lr_scheduler
from torch.utils.data import DataLoader, SequentialSampler, BatchSampler


def create_data_loader(dataset, batch_size, collate_fn):
    sampler = SequentialSampler(dataset)
    batch_sampler = BatchSampler(sampler, batch_size, drop_last=False)
    return DataLoader(dataset, batch_sampler=batch_sampler, collate_fn=collate_fn)


def load_reddit(train_split, val_split, min_len=50):
    """Concatenate the short and long reddit TIFU datasets and split into train, validation, and test sets. Keep only the docs and their summary."""
    dataset_short = load_dataset("reddit_tifu", "short")
    dataset_short = dataset_short.remove_columns(['ups', 'num_comments', 'upvote_ratio', 'score', 'tldr'])
    dataset_short = dataset_short.rename_columns({'documents': 'document', 'title': 'summary'})

    dataset_long = load_dataset("reddit_tifu", "long")
    dataset_long = dataset_long.remove_columns(['ups', 'num_comments', 'upvote_ratio', 'score', 'title'])
    dataset_long = dataset_long.rename_columns({'documents': 'document', 'tldr': 'summary'})

    dataset = concatenate_datasets([dataset_short["train"], dataset_long["train"]])

    # Filtering out too short documents and summaries
    dataset = dataset.filter(lambda x:
                             len(x["document"]) > min_len
                             and len(x["summary"]) > min_len
                             and len(x["document"]) > len(x["summary"]))

    # Adding a the doc length of each instance
    dataset = dataset.map(lambda x: {'doc_len': len(x['document'])})

    # Split the dataset into train, validation, and test sets after shuffling
    train_dataset, val_dataset, test_dataset = split_data(dataset, train_split, val_split)

    # Sort the datasets by document length
    train_dataset = train_dataset.sort('doc_len')
    val_dataset = val_dataset.sort('doc_len')
    test_dataset = test_dataset.sort('doc_len')

    return train_dataset, val_dataset, test_dataset


def split_data(dataset, train_split, val_split):
    # Shuffle the dataset
    dataset = dataset.shuffle()
    dataset = dataset.flatten_indices()  # rewrite the shuffled dataset on disk again as contiguous chunks for speed
    
    dataset = dataset.train_test_split(test_size=1-train_split)
    train_dataset = dataset['train']
    test_dataset = dataset['test'].train_test_split(test_size=1-(val_split/(1-train_split)))
    val_dataset = test_dataset['train']
    test_dataset = test_dataset['test']

    return train_dataset, val_dataset, test_dataset


def init_schedule(optimizer, sched, train_loader, lr, epochs, emb_dim):
    if sched == "constant" or sched == "none":
        scheduler = lr_scheduler.LambdaLR(optimizer, lr_lambda=lambda _: 1)
    elif sched == "cosineannealing":
        scheduler = lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=10, T_mult=1, eta_min=0.0, last_epoch=-1)
    elif sched == "invsqrt":
        scheduler = lr_scheduler.LambdaLR(optimizer, lr_lambda=lambda epoch: 1/math.sqrt(epoch) if epoch > 0 else 1)
    elif sched == "linear":
        scheduler = lr_scheduler.LinearLR(optimizer, start_factor=lr/5, end_factor=lr, total_iters=len(train_loader)*epochs)
    elif sched == "onecycle":
        scheduler = lr_scheduler.OneCycleLR(optimizer, max_lr=lr, total_steps=len(train_loader)*epochs, pct_start=0.3, anneal_strategy="linear")
    elif sched == "noam":  # TODO: write about this in the report
        warmup_steps = 0.3 * len(train_loader) * epochs
        scheduler = lr_scheduler.LambdaLR(optimizer, lr_lambda=lambda current_step: (emb_dim ** -0.5) * min((current_step+1) ** -0.5, (current_step+1) * (warmup_steps ** -1.5)))
    else:
        raise ValueError("Invalid scheduler option provided.")
    return scheduler


def batch_by_instances(device, sequences, labels, batch_size=32, pad_token=0):
    """Create batches of a given number of instances and pad all instances within a batch to be the same length.

    Args:
        device (torch.device): Device to load the tensors onto
        sequences (List): A list of input sequences
        labels (List): List of corresponding labels
        batch_size (int, optional): Number of instances in a batch. Defaults to 32.

    Returns:
        tuple: The padded input sequences and their corresponding output labels.
    """
    
    batches_x, batches_y = [], []

    for i in range(0, len(sequences), batch_size):
        batch_x = sequences[i:i + batch_size]
        batch_y = labels[i:i + batch_size]

        # Find the max length in the current batch
        max_len = max(len(x) for x in batch_x)

        # Pad sequences in the current batch and convert them to tensors, then stack them into a single tensor per batch
        padded_tensor_batch_x = torch.stack(
            [torch.LongTensor(seq + [pad_token] * (max_len - len(seq))).to(device) for seq in batch_x])

        # Convert labels to tensors and stack these into a single tensor per batch
        tensor_batch_y = torch.LongTensor(batch_y).to(device)

        batches_x.append(padded_tensor_batch_x)
        batches_y.append(tensor_batch_y)

    return batches_x, batches_y
